#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

import json
from ipaddress import IPv4Address, AddressValueError, IPv6Address
import base64
import sys

import boto3


class AuthorizationMissing(Exception):
    status = 401
    response = {"WWW-Authenticate": "Basic realm=dyndns53"}


class HostnameException(Exception):
    status = 404
    response = "nohost"


class AuthorizationException(Exception):
    status = 403
    response = "badauth"


class FQDNException(Exception):
    status = 400
    response = "notfqdn"


class BadAgentException(Exception):
    status = 400
    response = "badagent"


class AbuseException(Exception):
    status = 403
    response = "abuse"


conf = {
   '<username>:<password>': {
      'hosts': {
         '<host.example.com.>': {  # FQDN (don't forget trailing `.`)
            'aws_region': 'us-west-2',  # not actually important
            'zone_id': '<MY_ZONE_ID>',  # same zone ID as in `iam_policy`
            'record': {
               'ttl': 60,  # TTL in seconds; should be low for DDNS
               # 'type': 'A',  # Type is now inferred from IP type
            },
            'last_update': None, # not currently used
         }
      }
   }
}


# https://stackoverflow.com/a/56081104
def base64_encode(string: str) -> str:
    """
    Encodes the provided byte string into base64
    :param string: A byte string to be encoded. Pass in as b'string to encode'
    :return: a base64 encoded byte string
    """
    return base64.b64encode(string.encode('ascii')).decode('ascii')


def base64_decode_as_string(bytestring: bytes) -> str:
    """
    Decodes a base64 encoded byte string into a normal unencoded string
    :param bytestring: The encoded string
    :return: an ascii converted, unencoded string
    """
    bytestring = base64.b64decode(bytestring)
    return bytestring.decode('ascii')


def _parse_ip_v4(ipstring, force_global=True):
    try:
        ipv4 = IPv4Address(ipstring)
        if force_global and not ipv4.is_global:
            raise BadAgentException(f"Invalid IPv4 string: {ipstring}")
        else:
            return ipstring
    except AddressValueError:
        raise BadAgentException(f"Invalid IPv4 string: {ipstring}")


def _parse_ip_v6(ipstring, force_global=True):
    try:
        ipv6 = IPv6Address(ipstring)
        if force_global and not ipv6.is_global:
            raise BadAgentException(f"Invalid IPv6 string: {ipstring}")
        else:
            return ipstring
    except AddressValueError:
        raise BadAgentException(f"Invalid IPv6 string: {ipstring}")


def _parse_ip(ipstring, force_global=True):
    try:
        ipv4 = _parse_ip_v4(ipstring, force_global)
        return ipv4, "A"
    except BadAgentException:
        try:
            ipv6 = _parse_ip_v6(ipstring, force_global)
            return ipv6, "AAAA"
        except BadAgentException:
            raise BadAgentException(f"Invalid IP string: {ipstring}")


def r53_upsert(host, hostconf, ip, record_type):
    client53 = boto3.client('route53', 'eu-west-3')

    record_set = client53.list_resource_record_sets(
        HostedZoneId=hostconf['zone_id'],
        StartRecordName=host,
        StartRecordType=record_type,
        MaxItems='1'
    )

    old_ip = None
    if not record_set:
        logger.info(f"No existing record found for host {host} in zone {hostconf['zone_id']}")
    else:
        try:
            record = record_set['ResourceRecordSets'][0]
            if record['Name'] == host and record['Type'] == record_type:
                if len(record['ResourceRecords']) == 1:
                    for subrecord in record['ResourceRecords']:
                        old_ip = subrecord['Value']
                else:
                    raise ValueError(f"Multiple existing records found for host {host} in zone {hostconf['zone_id']}")
        except IndexError:
            raise ValueError(f"No existing record found for host {host} in zone {hostconf['zone_id']}")

    if old_ip == ip:
        logger.debug(f"Old IP same as new IP: {ip}")
        return False

    logger.debug(f"Old IP was: {old_ip}")
    return_status = client53.change_resource_record_sets(
        HostedZoneId=hostconf['zone_id'],
        ChangeBatch={
            'Changes': [
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': host,
                        'Type': record_type,
                        'TTL': hostconf['record']['ttl'],
                        'ResourceRecords': [
                            {
                                'Value': ip
                            }
                        ]
                    }
                }
            ]
        }
    )
    logger.debug(f"{return_status=}")

    return True


def _handler(event):
    if 'header' not in event:
        raise KeyError("Headers not populated properly. Check API Gateway configuration.")

    try:
        auth_header = event['header']['Authorization']
    except KeyError:
        raise AuthorizationMissing("Authorization required but not provided.")

    try:
        auth_user, auth_pass = (
            base64_decode_as_string(auth_header[len('Basic '):]).split(':'))
    except Exception:
        raise BadAgentException(f"Malformed basicauth string: {event['header']['Authorization']}")

    auth_string = ':'.join([auth_user, auth_pass])
    if auth_string not in conf:
        raise AuthorizationException("Bad username/password.")

    try:
        hosts = set(hostname if hostname.endswith('.') else hostname + '.'
                    for hostname in event['querystring']['hostname'].split(','))
    except KeyError:
        raise BadAgentException("Hostname(s) required but not provided.")

    if any(host not in conf[auth_string]['hosts'] for host in hosts):
        raise HostnameException()

    try:
        ip, record_type = _parse_ip(event['querystring']['myip'])
    except BadAgentException:
        ip, record_type = _parse_ip(event['context']['source-ip'])
        logger.debug(f"User provided IP address '{event['querystring']['myip']}' is not usable,"
                     f" using best-guess from $context: {ip}")

    if any(r53_upsert(host, conf[auth_string]['hosts'][host], ip, record_type) for host in hosts):
        return f"good {ip}"
    else:
        return f"nochg {ip}"


def lambda_handler(event, context):
    try:
        response = _handler(event)
    except Exception as exc:
        try:
            json_exc_status = {'status': exc.status, 'response': exc.response, 'additional': exc.message}
        except AttributeError:
            json_exc_status = {'status': 500, 'response': "911", 'additional': str(exc)}
        finally:
            raise type(exc)(type(exc)(json.dumps(json_exc_status))).with_traceback(sys.exc_info()[2])

    return {'status': 200, 'response': response}

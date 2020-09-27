#!/usr/bin/python

##########################################################################
# Copyright (C) 2020 Carmine Scarpitta
# (Consortium GARR and University of Rome "Tor Vergata")
# www.garr.it - www.uniroma2.it/netgroup
#
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Implementation of SRv6 Controller
#
# @author Carmine Scarpitta <carmine.scarpitta@uniroma2.it>
#


'''
Control-Plane functionalities for SRv6 Manager
'''

# General imports
import logging
import os

import grpc
from six import text_type

# Proto dependencies
import commons_pb2
import srv6_manager_pb2
# Controller dependencies
import srv6_manager_pb2_grpc
from controller import arangodb_driver
from controller import utils

# Global variables definition
#
#
# Logger reference
logging.basicConfig(level=logging.NOTSET)
logger = logging.getLogger(__name__)
# Default number of bits for the SID Locator
DEFAULT_LOCATOR_BITS = 32
# Default number of bits for the uSID identifier
DEFAULT_USID_ID_BITS = 16


# Parser for gRPC errors
def parse_grpc_error(err):
    '''
    Parse a gRPC error
    '''

    status_code = err.code()
    details = err.details()
    logger.error('gRPC client reported an error: %s, %s',
                 status_code, details)
    if grpc.StatusCode.UNAVAILABLE == status_code:
        code = commons_pb2.STATUS_GRPC_SERVICE_UNAVAILABLE
    elif grpc.StatusCode.UNAUTHENTICATED == status_code:
        code = commons_pb2.STATUS_GRPC_UNAUTHORIZED
    else:
        code = commons_pb2.STATUS_INTERNAL_ERROR
    # Return an error message
    return code


def del_srv6_path_db(channel, destination, segments=None,
                     device='', encapmode="encap", table=-1, metric=-1,
                     bsid_addr='', fwd_engine='linux', key=None,
                     update_db=True):
    if not os.getenv('ENABLE_PERSISTENCY') in ['true', 'True']:
        return commons_pb2.STATUS_INTERNAL_ERROR
    # ArangoDB params
    arango_url = os.getenv('ARANGO_URL')
    arango_user = os.getenv('ARANGO_USER')
    arango_password = os.getenv('ARANGO_PASSWORD')
    # Connect to ArangoDB
    client = arangodb_driver.connect_arango(
        url=arango_url)  # TODO keep arango connection open
    # Connect to the db
    database = arangodb_driver.connect_srv6_usid_db(
        client=client,
        username=arango_user,
        password=arango_password
    )
    # Find the paths matching the params
    srv6_paths = arangodb_driver.find_srv6_path(
        database=database,
        key=key,
        grpc_address=utils.grpc_chan_to_addr_port(channel)[0],
        grpc_port=utils.grpc_chan_to_addr_port(channel)[1],
        destination=destination,
        segments=segments,
        device=device,
        encapmode=encapmode,
        table=table,
        metric=metric,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    if len(srv6_paths) == 0:
        # Entity not found
        logger.error('Entity not found')
        return commons_pb2.STATUS_NO_SUCH_PROCESS
    # Remove the paths
    for srv6_path in srv6_paths:
        # Initialize segments list
        if srv6_path['segments'] is None:
            segments = []
        # Create request message
        request = srv6_manager_pb2.SRv6ManagerRequest()
        # Create a new SRv6 path request
        path_request = request.srv6_path_request       # pylint: disable=no-member
        # Create a new path
        path = path_request.paths.add()
        # Set destination
        path.destination = text_type(srv6_path['destination'])
        # Set device
        # If the device is not specified (i.e. empty string),
        # it will be chosen by the gRPC server
        path.device = text_type(srv6_path['device'])
        # Set table ID
        # If the table ID is not specified (i.e. table=-1),
        # the main table will be used
        path.table = int(srv6_path['table'])
        # Set metric (i.e. preference value of the route)
        # If the metric is not specified (i.e. metric=-1),
        # the decision is left to the Linux kernel
        path.metric = int(srv6_path['metric'])
        # Set the BSID address (required for VPP)
        path.bsid_addr = str(srv6_path['bsid_addr'])
        # Get gRPC channel
        channel = utils.get_grpc_session(
            server_ip=srv6_path['grpc_address'],
            server_port=srv6_path['grpc_port']
        )
        # Get the reference of the stub
        stub = srv6_manager_pb2_grpc.SRv6ManagerStub(channel)
        # Remove the SRv6 path
        response = stub.Remove(request)
        # Get the status code of the gRPC operation
        response = response.status
        # Remove the path from the db
        arangodb_driver.delete_srv6_path(
            database=database,
            key=srv6_path['_key'],
            grpc_address=srv6_path['grpc_address'],
            grpc_port=srv6_path['grpc_port'],
            destination=srv6_path['destination'],
            segments=srv6_path['segments'],
            device=srv6_path['device'],
            encapmode=srv6_path['encapmode'],
            table=srv6_path['table'],
            metric=srv6_path['metric'],
            bsid_addr=srv6_path['bsid_addr'],
            fwd_engine=srv6_path['fwd_engine']
        )
    # Done, return the reply
    return response


def handle_srv6_path(operation, channel, destination, segments=None,
                     device='', encapmode="encap", table=-1, metric=-1,
                     bsid_addr='', fwd_engine='linux', key=None,
                     update_db=True):
    '''
    Handle a SRv6 Path
    '''

    # pylint: disable=too-many-locals, too-many-arguments, too-many-branches

    if segments is None:
        segments = []
    # Create request message
    request = srv6_manager_pb2.SRv6ManagerRequest()
    # Create a new SRv6 path request
    path_request = request.srv6_path_request       # pylint: disable=no-member
    # Create a new path
    path = path_request.paths.add()
    # Set destination
    path.destination = text_type(destination)
    # Set device
    # If the device is not specified (i.e. empty string),
    # it will be chosen by the gRPC server
    path.device = text_type(device)
    # Set table ID
    # If the table ID is not specified (i.e. table=-1),
    # the main table will be used
    path.table = int(table)
    # Set metric (i.e. preference value of the route)
    # If the metric is not specified (i.e. metric=-1),
    # the decision is left to the Linux kernel
    path.metric = int(metric)
    # Set the BSID address (required for VPP)
    path.bsid_addr = str(bsid_addr)
    # Handle SRv6 policy for VPP
    if fwd_engine == 'vpp':
        if bsid_addr == '':
            logger.error('"bsid_addr" argument is mandatory for VPP')
            return None
        # Handle SRv6 policy
        res = handle_srv6_policy(
            operation=operation,
            channel=channel,
            bsid_addr=bsid_addr,
            segments=segments,
            table=table,
            metric=metric,
            fwd_engine=fwd_engine
        )
        if res != commons_pb2.STATUS_SUCCESS:
            logger.error('Cannot create SRv6 policy: error %s', res)
            return None
    # Forwarding engine (Linux or VPP)
    try:
        path_request.fwd_engine = srv6_manager_pb2.FwdEngine.Value(fwd_engine.upper())
    except ValueError:
        logger.error('Invalid forwarding engine: %s', fwd_engine)
        return None
    try:
        # Get the reference of the stub
        stub = srv6_manager_pb2_grpc.SRv6ManagerStub(channel)
        # Fill the request depending on the operation
        # and send the request
        if operation == 'add':
            # Set encapmode
            path.encapmode = text_type(encapmode)
            if len(segments) == 0:
                logger.error('*** Missing segments for seg6 route')
                return commons_pb2.STATUS_INTERNAL_ERROR
            # Iterate on the segments and build the SID list
            for segment in segments:
                # Append the segment to the SID list
                srv6_segment = path.sr_path.add()
                srv6_segment.segment = text_type(segment)
            # Create the SRv6 path
            response = stub.Create(request)
            # Get the status code of the gRPC operation
            response = response.status
            # Store the path to the database
            if response == commons_pb2.STATUS_SUCCESS and \
                    os.getenv('ENABLE_PERSISTENCY') in ['true', 'True'] and \
                    update_db:
                # ArangoDB params
                arango_url = os.getenv('ARANGO_URL')
                arango_user = os.getenv('ARANGO_USER')
                arango_password = os.getenv('ARANGO_PASSWORD')
                # Connect to ArangoDB
                client = arangodb_driver.connect_arango(
                    url=arango_url)  # TODO keep arango connection open
                # Connect to the db
                database = arangodb_driver.connect_srv6_usid_db(
                    client=client,
                    username=arango_user,
                    password=arango_password
                )
                # Save the policy to the db
                arangodb_driver.insert_srv6_path(
                    database=database,
                    key=key,
                    grpc_address=utils.grpc_chan_to_addr_port(channel)[0],
                    grpc_port=utils.grpc_chan_to_addr_port(channel)[1],
                    destination=destination,
                    segments=segments,
                    device=device,
                    encapmode=encapmode,
                    table=table,
                    metric=metric,
                    bsid_addr=bsid_addr,
                    fwd_engine=fwd_engine
                )
        elif operation == 'get':    # TODO db
            # Get the SRv6 path
            response = stub.Get(request)
            # Get the status code of the gRPC operation
            response = response.status
        elif operation == 'change':
            # Set encapmode
            path.encapmode = text_type(encapmode)
            # Iterate on the segments and build the SID list
            for segment in segments:
                # Append the segment to the SID list
                srv6_segment = path.sr_path.add()
                srv6_segment.segment = text_type(segment)
            # Update the SRv6 path
            response = stub.Update(request)
            # Get the status code of the gRPC operation
            response = response.status
            # Remove the path from the database
            if response == commons_pb2.STATUS_SUCCESS and \
                    os.getenv('ENABLE_PERSISTENCY') in ['true', 'True'] and \
                    update_db:
                # ArangoDB params
                arango_url = os.getenv('ARANGO_URL')
                arango_user = os.getenv('ARANGO_USER')
                arango_password = os.getenv('ARANGO_PASSWORD')
                # Connect to ArangoDB
                client = arangodb_driver.connect_arango(
                    url=arango_url)  # TODO keep arango connection open
                # Connect to the db
                database = arangodb_driver.connect_srv6_usid_db(
                    client=client,
                    username=arango_user,
                    password=arango_password
                )
                # Save the policy to the db
                arangodb_driver.update_srv6_path(
                    database=database,
                    key=key,
                    grpc_address=utils.grpc_chan_to_addr_port(channel)[0],
                    grpc_port=utils.grpc_chan_to_addr_port(channel)[1],
                    destination=destination,
                    segments=segments,
                    device=device,
                    encapmode=encapmode,
                    table=table,
                    metric=metric,
                    bsid_addr=bsid_addr,
                    fwd_engine=fwd_engine
                )
        elif operation == 'del':
            # Remove the SRv6 path
            if os.getenv('ENABLE_PERSISTENCY') in ['true', 'True']:
                response = del_srv6_path_db(
                    channel=channel,
                    destination=destination,
                    segments=segments,
                    device=device,
                    encapmode=encapmode,
                    table=table,
                    metric=metric,
                    bsid_addr=bsid_addr,
                    fwd_engine=fwd_engine,
                    key=key,
                    update_db=update_db
                )
            else:
                # Remove the SRv6 path
                response = stub.Remove(request)
                # Get the status code of the gRPC operation
                response = response.status
        else:
            # Operation not supported
            logger.error('Operation not supported')
            response = commons_pb2.STATUS_OPERATION_NOT_SUPPORTED
    except grpc.RpcError as err:
        # An error occurred during the gRPC operation
        # Parse the error and return it
        response = parse_grpc_error(err)
    # Return the response
    return response


def handle_srv6_policy(operation, channel, bsid_addr, segments=None,
                       table=-1, metric=-1, fwd_engine='linux'):
    '''
    Handle a SRv6 Path
    '''

    # pylint: disable=too-many-locals, too-many-arguments

    if segments is None:
        segments = []
    # Create request message
    request = srv6_manager_pb2.SRv6ManagerRequest()
    # Create a new SRv6 path request
    policy_request = request.srv6_policy_request   # pylint: disable=no-member
    # Create a new path
    policy = policy_request.policies.add()
    # Set BSID address
    policy.bsid_addr = text_type(bsid_addr)
    # Set table ID
    # If the table ID is not specified (i.e. table=-1),
    # the main table will be used
    policy.table = int(table)
    # Set metric (i.e. preference value of the route)
    # If the metric is not specified (i.e. metric=-1),
    # the decision is left to the Linux kernel
    policy.metric = int(metric)
    # Forwarding engine (Linux or VPP)
    try:
        policy_request.fwd_engine = srv6_manager_pb2.FwdEngine.Value(
            fwd_engine.upper())
    except ValueError:
        logger.error('Invalid forwarding engine: %s', fwd_engine)
        return None
    try:
        # Get the reference of the stub
        stub = srv6_manager_pb2_grpc.SRv6ManagerStub(channel)
        # Fill the request depending on the operation
        # and send the request
        if operation == 'add':
            if len(segments) == 0:
                logger.error('*** Missing segments for seg6 route')
                return commons_pb2.STATUS_INTERNAL_ERROR
            # Iterate on the segments and build the SID list
            for segment in segments:
                # Append the segment to the SID list
                srv6_segment = policy.sr_path.add()
                srv6_segment.segment = text_type(segment)
            # Create the SRv6 path
            response = stub.Create(request)
        elif operation == 'get':
            # Get the SRv6 path
            response = stub.Get(request)
        elif operation == 'change':
            # Iterate on the segments and build the SID list
            for segment in segments:
                # Append the segment to the SID list
                srv6_segment = policy.sr_path.add()
                srv6_segment.segment = text_type(segment)
            # Update the SRv6 path
            response = stub.Update(request)
        elif operation == 'del':
            # Remove the SRv6 path
            response = stub.Remove(request)
        # Get the status code of the gRPC operation
        response = response.status
    except grpc.RpcError as err:
        # An error occurred during the gRPC operation
        # Parse the error and return it
        response = parse_grpc_error(err)
    # Return the response
    return response


def handle_srv6_behavior(operation, channel, segment, action='', device='',
                         table=-1, nexthop="", lookup_table=-1,
                         interface="", segments=None, metric=-1,
                         fwd_engine='linux'):
    '''
    Handle a SRv6 behavior
    '''
    # pylint: disable=too-many-arguments, too-many-locals
    #
    if segments is None:
        segments = []
    # Create request message
    request = srv6_manager_pb2.SRv6ManagerRequest()
    # Create a new SRv6 behavior request
    behavior_request = (request               # pylint: disable=no-member
                        .srv6_behavior_request)
    # Create a new SRv6 behavior
    behavior = behavior_request.behaviors.add()
    # Set local segment for the seg6local route
    behavior.segment = text_type(segment)
    # Set the device
    # If the device is not specified (i.e. empty string),
    # it will be chosen by the gRPC server
    behavior.device = text_type(device)
    # Set the table where the seg6local must be inserted
    # If the table ID is not specified (i.e. table=-1),
    # the main table will be used
    behavior.table = int(table)
    # Set device
    # If the device is not specified (i.e. empty string),
    # it will be chosen by the gRPC server
    behavior.device = text_type(device)
    # Set metric (i.e. preference value of the route)
    # If the metric is not specified (i.e. metric=-1),
    # the decision is left to the Linux kernel
    behavior.metric = int(metric)
    # Forwarding engine (Linux or VPP)
    try:
        behavior_request.fwd_engine = srv6_manager_pb2.FwdEngine.Value(
            fwd_engine.upper())
    except ValueError:
        logger.error('Invalid forwarding engine: %s', fwd_engine)
        return None
    try:
        # Get the reference of the stub
        stub = srv6_manager_pb2_grpc.SRv6ManagerStub(channel)
        # Fill the request depending on the operation
        # and send the request
        if operation == 'add':
            if action == '':
                logger.error('*** Missing action for seg6local route')
                return commons_pb2.STATUS_INTERNAL_ERROR
            # Set the action for the seg6local route
            behavior.action = text_type(action)
            # Set the nexthop for the L3 cross-connect actions
            # (e.g. End.DX4, End.DX6)
            behavior.nexthop = text_type(nexthop)
            # Set the table for the "decap and table lookup" actions
            # (e.g. End.DT4, End.DT6)
            behavior.lookup_table = int(lookup_table)
            # Set the inteface for the L2 cross-connect actions
            # (e.g. End.DX2)
            behavior.interface = text_type(interface)
            # Set the segments for the binding SID actions
            # (e.g. End.B6, End.B6.Encaps)
            for seg in segments:
                # Create a new segment
                srv6_segment = behavior.segs.add()
                srv6_segment.segment = text_type(seg)
            # Create the SRv6 behavior
            response = stub.Create(request)
        elif operation == 'get':
            # Get the SRv6 behavior
            response = stub.Get(request)
        elif operation == 'change':
            # Set the action for the seg6local route
            behavior.action = text_type(action)
            # Set the nexthop for the L3 cross-connect actions
            # (e.g. End.DX4, End.DX6)
            behavior.nexthop = text_type(nexthop)
            # Set the table for the "decap and table lookup" actions
            # (e.g. End.DT4, End.DT6)
            behavior.lookup_table = int(lookup_table)
            # Set the inteface for the L2 cross-connect actions
            # (e.g. End.DX2)
            behavior.interface = text_type(interface)
            # Set the segments for the binding SID actions
            # (e.g. End.B6, End.B6.Encaps)
            for seg in segments:
                # Create a new segment
                srv6_segment = behavior.segs.add()
                srv6_segment.segment = text_type(seg)
            # Update the SRv6 behavior
            response = stub.Update(request)
        elif operation == 'del':
            # Remove the SRv6 behavior
            response = stub.Remove(request)
        else:
            logger.error('Invalid operation: %s', operation)
            return None
        # Get the status code of the gRPC operation
        response = response.status
    except grpc.RpcError as err:
        # An error occurred during the gRPC operation
        # Parse the error and return it
        response = parse_grpc_error(err)
    # Return the response
    return response


class SRv6Exception(Exception):
    '''
    Generic SRv6 Exception.
    '''


def create_uni_srv6_tunnel(ingress_channel, egress_channel,
                           destination, segments, localseg=None,
                           bsid_addr='', fwd_engine='linux'):
    '''
    Create a unidirectional SRv6 tunnel from <ingress> to <egress>

    :param ingress_channel: The gRPC Channel to the ingress node
    :type ingress_channel: class: `grpc._channel.Channel`
    :param egress_channel: The gRPC Channel to the egress node
    :type egress_channel: class: `grpc._channel.Channel`
    :param destination: The destination prefix of the SRv6 path.
                  It can be a IP address or a subnet.
    :type destination: str
    :param segments: The SID list to be applied to the packets going to
                     the destination
    :type segments: list
    :param localseg: The local segment to be associated to the End.DT6
                     seg6local function on the egress node. If the argument
                     'localseg' isn't passed in, the End.DT6 function
                     is not created.
    :type localseg: str, optional
    :param fwd_engine: Forwarding engine for the SRv6 route. Default: Linux.
    :type fwd_engine: str, optional
    '''
    # pylint: disable=too-many-arguments
    #
    # Add seg6 route to <ingress> to steer the packets sent to the
    # <destination> through the SID list <segments>
    #
    # Equivalent to the command:
    #    ingress: ip -6 route add <destination> encap seg6 mode encap \
    #            segs <segments> dev <device>
    res = handle_srv6_path(
        operation='add',
        channel=ingress_channel,
        destination=destination,
        segments=segments,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # Pretty print status code
    utils.print_status_message(
        status_code=res,
        success_msg='Added SRv6 Path',
        failure_msg='Error in add_srv6_path()'
    )
    # If an error occurred, abort the operation
    if res != commons_pb2.STATUS_SUCCESS:
        return res
    # Perform "Decapsulaton and Specific IPv6 Table Lookup" function
    # on the egress node <egress>
    # The decap function is associated to the <localseg> passed in
    # as argument. If argument 'localseg' isn't passed in, the behavior
    # is not added
    #
    # Equivalent to the command:
    #    egress: ip -6 route add <localseg> encap seg6local action \
    #            End.DT6 table 254 dev <device>
    if localseg is not None:
        res = handle_srv6_behavior(
            operation='add',
            channel=egress_channel,
            segment=localseg,
            action='End.DT6',
            lookup_table=254,
            fwd_engine=fwd_engine
        )
        # Pretty print status code
        utils.print_status_message(
            status_code=res,
            success_msg='Added SRv6 Behavior',
            failure_msg='Error in add_srv6_behavior()'
        )
        # If an error occurred, abort the operation
        if res != commons_pb2.STATUS_SUCCESS:
            return res
    # Success
    return commons_pb2.STATUS_SUCCESS


def create_srv6_tunnel(node_l_channel, node_r_channel,
                       sidlist_lr, sidlist_rl, dest_lr, dest_rl,
                       localseg_lr=None, localseg_rl=None,
                       bsid_addr='', fwd_engine='linux'):
    '''
    Create a bidirectional SRv6 tunnel between <node_l> and <node_r>.

    :param node_l_channel: The gRPC Channel to the left endpoint (node_l)
                           of the SRv6 tunnel
    :type node_l_channel: class: `grpc._channel.Channel`
    :param node_r_channel: The gRPC Channel to the right endpoint (node_r)
                           of the SRv6 tunnel
    :type node_r_channel: class: `grpc._channel.Channel`
    :param sidlist_lr: The SID list to be installed on the packets going
                       from <node_l> to <node_r>
    :type sidlist_lr: list
    :param sidlist_rl: The SID list to be installed on the packets going
                       from <node_r> to <node_l>
    :type sidlist_rl: list
    :param dest_lr: The destination prefix of the SRv6 path from <node_l>
                    to <node_r>. It can be a IP address or a subnet.
    :type dest_lr: str
    :param dest_rl: The destination prefix of the SRv6 path from <node_r>
                    to <node_l>. It can be a IP address or a subnet.
    :type dest_rl: str
    :param localseg_lr: The local segment to be associated to the End.DT6
                        seg6local function for the SRv6 path from <node_l>
                        to <node_r>. If the argument 'localseg_lr' isn't
                        passed in, the End.DT6 function is not created.
    :type localseg_lr: str, optional
    :param localseg_rl: The local segment to be associated to the End.DT6
                        seg6local function for the SRv6 path from <node_r>
                        to <node_l>. If the argument 'localseg_rl' isn't
                        passed in, the End.DT6 function is not created.
    :type localseg_rl: str, optional
    :param fwd_engine: Forwarding engine for the SRv6 route. Default: Linux.
    :type fwd_engine: str, optional
    '''
    # pylint: disable=too-many-arguments
    #
    # Create a unidirectional SRv6 tunnel from <node_l> to <node_r>
    res = create_uni_srv6_tunnel(
        ingress_channel=node_l_channel,
        egress_channel=node_r_channel,
        destination=dest_lr,
        segments=sidlist_lr,
        localseg=localseg_lr,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # If an error occurred, abort the operation
    if res != commons_pb2.STATUS_SUCCESS:
        return res
    # Create a unidirectional SRv6 tunnel from <node_r> to <node_l>
    res = create_uni_srv6_tunnel(
        ingress_channel=node_r_channel,
        egress_channel=node_l_channel,
        destination=dest_rl,
        segments=sidlist_rl,
        localseg=localseg_rl,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # If an error occurred, abort the operation
    if res != commons_pb2.STATUS_SUCCESS:
        return res
    # Success
    return commons_pb2.STATUS_SUCCESS


def destroy_uni_srv6_tunnel(ingress_channel, egress_channel, destination,
                            localseg=None, bsid_addr='', fwd_engine='linux',
                            ignore_errors=False):
    '''
    Destroy a unidirectional SRv6 tunnel from <ingress> to <egress>.

    :param ingress_channel: The gRPC Channel to the ingress node
    :type ingress_channel: class: `grpc._channel.Channel`
    :param egress_channel: The gRPC Channel to the egress node
    :type egress_channel: class: `grpc._channel.Channel`
    :param destination: The destination prefix of the SRv6 path.
                        It can be a IP address or a subnet.
    :type destination: str
    :param localseg: The local segment associated to the End.DT6 seg6local
                     function on the egress node. If the argument 'localseg'
                     isn't passed in, the End.DT6 function is not removed.
    :type localseg: str, optional
    :param fwd_engine: Forwarding engine for the SRv6 route. Default: Linux.
    :type fwd_engine: str, optional
    :param ignore_errors: Whether to ignore "No such process" errors or not
                          (default is False)
    :type ignore_errors: bool, optional
    '''
    # pylint: disable=too-many-arguments
    #
    # Remove seg6 route from <ingress> to steer the packets sent to
    # <destination> through the SID list <segments>
    #
    # Equivalent to the command:
    #    ingress: ip -6 route del <destination> encap seg6 mode encap \
    #             segs <segments> dev <device>
    res = handle_srv6_path(
        operation='del',
        channel=ingress_channel,
        destination=destination,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # Pretty print status code
    utils.print_status_message(
        status_code=res,
        success_msg='Removed SRv6 Path',
        failure_msg='Error in remove_srv6_path()'
    )
    # If an error occurred, abort the operation
    if res == commons_pb2.STATUS_NO_SUCH_PROCESS:
        # If the 'ignore_errors' flag is set, continue
        if not ignore_errors:
            return res
    elif res != commons_pb2.STATUS_SUCCESS:
        return res
    # Remove "Decapsulaton and Specific IPv6 Table Lookup" function
    # from the egress node <egress>
    # The decap function associated to the <localseg> passed in
    # as argument. If argument 'localseg' isn't passed in, the behavior
    # is not removed
    #
    # Equivalent to the command:
    #    egress: ip -6 route del <localseg> encap seg6local action \
    #            End.DT6 table 254 dev <device>
    if localseg is not None:
        res = handle_srv6_behavior(
            operation='del',
            channel=egress_channel,
            segment=localseg,
            fwd_engine=fwd_engine
        )
        # Pretty print status code
        utils.print_status_message(
            status_code=res,
            success_msg='Removed SRv6 behavior',
            failure_msg='Error in remove_srv6_behavior()'
        )
        # If an error occurred, abort the operation
        if res == commons_pb2.STATUS_NO_SUCH_PROCESS:
            # If the 'ignore_errors' flag is set, continue
            if not ignore_errors:
                return res
        elif res != commons_pb2.STATUS_SUCCESS:
            return res
    # Success
    return commons_pb2.STATUS_SUCCESS


def destroy_srv6_tunnel(node_l_channel, node_r_channel,
                        dest_lr, dest_rl, localseg_lr=None, localseg_rl=None,
                        bsid_addr='', fwd_engine='linux',
                        ignore_errors=False):
    '''
    Destroy a bidirectional SRv6 tunnel between <node_l> and <node_r>.

    :param node_l_channel: The gRPC channel to the left endpoint of the
                           SRv6 tunnel (node_l)
    :type node_l_channel: class: `grpc._channel.Channel`
    :param node_r_channel: The gRPC channel to the right endpoint of the
                           SRv6 tunnel (node_r)
    :type node_r_channel: class: `grpc._channel.Channel`
    :param node_l: The IP address of the left endpoint of the SRv6 tunnel
    :type node_l: str
    :param node_r: The IP address of the right endpoint of the SRv6 tunnel
    :type node_r: str
    :param dest_lr: The destination prefix of the SRv6 path from <node_l>
                    to <node_r>. It can be a IP address or a subnet.
    :type dest_lr: str
    :param dest_rl: The destination prefix of the SRv6 path from <node_r>
                    to <node_l>. It can be a IP address or a subnet.
    :type dest_rl: str
    :param localseg_lr: The local segment associated to the End.DT6 seg6local
                        function for the SRv6 path from <node_l> to <node_r>.
                        If the argument 'localseg_l' isn't passed in, the
                        End.DT6 function is not removed.
    :type localseg_lr: str, optional
    :param localseg_rl: The local segment associated to the End.DT6 seg6local
                        function for the SRv6 path from <node_r> to <node_l>.
                        If the argument 'localseg_r' isn't passed in, the
                        End.DT6 function is not removed.
    :type localseg_rl: str, optional
    :param fwd_engine: Forwarding engine for the SRv6 route. Default: Linux.
    :type fwd_engine: str, optional
    :param ignore_errors: Whether to ignore "No such process" errors or not
                          (default is False)
    :type ignore_errors: bool, optional
    '''
    # pylint: disable=too-many-arguments
    #
    # Remove unidirectional SRv6 tunnel from <node_l> to <node_r>
    res = destroy_uni_srv6_tunnel(
        ingress_channel=node_l_channel,
        egress_channel=node_r_channel,
        destination=dest_lr,
        localseg=localseg_lr,
        ignore_errors=ignore_errors,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # If an error occurred, abort the operation
    if res != commons_pb2.STATUS_SUCCESS:
        return res
    # Remove unidirectional SRv6 tunnel from <node_r> to <node_l>
    res = destroy_uni_srv6_tunnel(
        ingress_channel=node_r_channel,
        egress_channel=node_l_channel,
        destination=dest_rl,
        localseg=localseg_rl,
        ignore_errors=ignore_errors,
        bsid_addr=bsid_addr,
        fwd_engine=fwd_engine
    )
    # If an error occurred, abort the operation
    if res != commons_pb2.STATUS_SUCCESS:
        return res
    # Success
    return commons_pb2.STATUS_SUCCESS

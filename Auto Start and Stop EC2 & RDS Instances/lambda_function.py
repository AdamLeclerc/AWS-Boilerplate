#!/usr/bin/env python3
import boto3
import datetime
import json
import logging
import os
import time


# Output logging - default WARNING. Set to INFO for full output in cloudwatch
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# AWS Tags to target for starting and stopping
try:
    start = os.environ['START_TAG']
except Exception:
    start = 'autoOrc-up'
    log.info('No environment variable set for \'START_TAG\', using default')
try:
    stop = os.environ['STOP_TAG']
except Exception:
    stop = 'autoOrc-down'
    log.info('No environment variable set for \'STOP_TAG\', using default')

# Start instances only on weekends? (set to True to start every day)
try:
    weekends = os.environ['START_WEEKENDS']
except Exception:
    weekends = False
    log.info('No flag for \'START_WEEKENDS\' set')


# Main function that lambda calls
def lambda_handler(event, context):
    thisLambda = context.function_name

    # Create cloudwatch metrics for instance start/stop/failure
    def put_cloudwatch_metric(MetricName, value, process, outcome):
        cw.put_metric_data(
            Namespace=f'{thisLambda}-Results',
            MetricData=[{
                'MetricName': MetricName,
                'Value': value,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'Process', 'Value': process},
                    {'Name': 'Outcome', 'Value': outcome}
                ]
            }]
        )

    # Get all available AWS regions
    def get_ec2_regions():
        session = boto3.session.Session()
        return(session.get_available_regions('ec2'))

    startTag = 'tag:' + start
    stopTag = 'tag:' + stop
    awsID = boto3.client('sts').get_caller_identity().get('Account')

    # Check to see if today is a weekday
    def weekday(test_date):
        if test_date.isoweekday() in range(1, 6):
            return(True)
        else:
            return(False)

    isWeekday = weekday(datetime.datetime.now())

    # Define a timer, used to gague shutdown time, in UTC
    timer = time.strftime("%H:%M")

    # Set base filters for running/stopped instances, and matching orc tags
    FilterRunning = [
        {'Name': 'instance-state-name', 'Values': ['running']},
        {'Name': stopTag, 'Values': [timer]}
    ]

    FilterStopped = [
        {'Name': 'instance-state-name', 'Values': ['stopped']},
        {'Name': startTag, 'Values': [timer]}
    ]

    counter = 0
    errCount = 0

    # On initial lambda run, spawn regional AutoOrcs
    if 'REGION_NAME' not in event.keys():
        thisRegion = boto3.session.Session().region_name
        log.info(f'\n[ {thisLambda} initializing at {timer} in {thisRegion}]')

        # below regions aren't enabled, but are avilable, in US AWS by default:
        #   Africa (Cape Town):	af-south-1
        #   Asia Pacific (Hong Kong):	ap-east-1
        #   Europe (Milan):	eu-south-1
        #   Middle East (Bahrain):	me-south-1
        notEnabled = ['me-south-1', 'ap-east-1', 'af-south-1', 'eu-south-1']

        for region in get_ec2_regions():
            if region not in notEnabled:
                resource = f'arn:aws:lambda:{thisRegion}:{awsID}:{thisLambda}'
                try:
                    resp = boto3.client('lambda').invoke(
                        FunctionName=resource,
                        InvocationType='Event',
                        Payload=json.dumps({'REGION_NAME': region})
                    )
                    response = True
                    log.info(f'Invoked {thisLambda} targeting {region} region')

                except Exception as e:
                    log.error(f'FAILED to run {thisLambda} in {region} - {e}')

    # If spawned from inital Lambda run, connect to the passed REGION_NAME
    else:
        # Define boto3 connections/variables
        region = event['REGION_NAME']
        log.info(f'\n[ {thisLambda} start time : {timer} in {region} ]')
        localSession = boto3.session.Session(region_name=region)
        cw = localSession.client('cloudwatch')
        rds = localSession.client('rds')
        ec2 = localSession.resource('ec2')

        # Find the name tag of an instance
        def get_ec2_instance_name(InstID):
            instName = None
            unnamedLabel = '(no \'name\' Tag)'
            ec2Inst = ec2.Instance(InstID)
            if ec2Inst.tags is not None:
                for tags in ec2Inst.tags:
                    if tags['Key'] == 'Name':
                        instName = tags['Value']
            if instName is None or instName == '':
                instName = unnamedLabel
            return(instName)

        # Get AutoOrc-down / AutoOrc-up tags on RDS instances
        def get_rds_orc_tags(ARN, phase):
            orcTimer = ''
            tags = rds.list_tags_for_resource(ResourceName=ARN)

            for tag in tags['TagList']:
                if tag['Key'] == phase:
                    orcTimer = tag['Value']

            return(orcTimer)

        # Find and shutdown matching EC2 instances
        try:
            orcInstDown = ec2.instances.filter(Filters=FilterRunning)
            for instance in orcInstDown:
                counter += 1
                stateCode = 0
                name = get_ec2_instance_name(instance.id)
                log.info(f' - Stopping Instance-ID: {instance.id} Name : {name}')
                resp = instance.stop()
                stateCode = resp['StoppingInstances'][0]['CurrentState']['Code']

                if stateCode == 16:
                    errCount += 1
                    log.error(f'ErrorCode # {stateCode} stopping: {name}')

            if (counter > 0):
                put_cloudwatch_metric(awsID, counter, stop, 'Success')

            if (errCount > 0):
                put_cloudwatch_metric(awsID, error_counter, stop, 'Error')
                log.error(f'x - Errors stopping {error_counter} instances')

            log.info(f'\t[ Stopped {counter} instances in {region} ]')
        except Exception as e:
            log.error(f'Unable to stop instance in {region} due to:\n{e}')

        # Find and start matching EC2 instances
        try:
            OrcInstUp = ec2.instances.filter(Filters=FilterStopped)
            counter = 0
            errCount = 0
            badStartCodes = ['32', '48', '64', '80']

            # Cycle through and start tagged EC2 instances
            if isWeekday or weekends is True:
                for instance in OrcInstUp:
                    counter += 1
                    stateCode = 0
                    name = get_ec2_instance_name(instance.id)
                    log.info(f'- Start Instance-ID: {instance.id}  Name: {name}')
                    resp = instance.start()
                    stateCode = resp['StartingInstances'][0]['CurrentState']['Code']

                    if stateCode in badStartCodes:
                        errCount += 1
                        log.error(f'ErrorCode # {stateCode} starting: {name}')

                if (counter > 0):
                    put_cloudwatch_metric(awsID, counter, start, 'Success')

                if (errCount > 0):
                    put_cloudwatch_metric(awsID, error_counter, start, 'Error')
                    log.error(f'x - Errors starting {error_counter} instances')
            else:
                log.info('program set to not start instances on weekends!')

            log.info(f'\t[ Started {counter} instances in {region} ]')
        except Exception as e:
            log.error(f'Unable to start instance in {region} due to:\n{e}')
        # Cycle through all RDS instaces, starting/stopping Orc tagged ones
        try:
            orcRDS = rds.describe_db_instances()
            counter = 0
            for rdsInst in orcRDS['DBInstances']:
                rdsName = str(rdsInst['DBInstanceIdentifier'])
                rdsARN = str(rdsInst['DBInstanceArn'])
                rdsStatus = str(rdsInst['DBInstanceStatus'])
                rdsAZstate = str(rdsInst['MultiAZ'])

                if isWeekday or weekends is True:

                    if rdsAZstate == 'False' and rdsStatus == 'stopped':
                        orcUp = get_rds_orc_tags(rdsARN, start)

                        if orcUp == timer:
                            log.info(f'RDS : {rdsName} database is starting up')
                            rds.start_db_instance(DBInstanceIdentifier=rdsName)
                            counter += 1
                else:
                    log.info('program set to not start RDS on weekends!')

                if rdsAZstate == 'False' and rdsStatus == 'available':
                    orcDown = get_rds_orc_tags(rdsARN, stop)

                    if orcDown == timer:
                        log.info(f'RDS: {rdsName} is shutting down now')
                        rds.stop_db_instance(DBInstanceIdentifier=rdsName)
                        counter += 1
            log.info(f'\t[ Started & Stopped {counter} RDS DBs in {region} ]')
        except Exception as e:
            log.error(f'Unable to start/stop RDS in {region} due to:\n{e}')
        log.info(f'[ {thisLambda} finished in {region} ]\n')

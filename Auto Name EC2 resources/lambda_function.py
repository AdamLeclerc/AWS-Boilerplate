#!/usr/bin/env python3
import json
import boto3
import logging
import time
import datetime


# Output logging - Set to INFO for full output in cloudwatch
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# Define boto3 connections/variables
ec2 = boto3.resource('ec2')
# Getting the Account ID needed to filter snapshots/AMIs
myAWSID = boto3.client('sts').get_caller_identity().get('Account')

# Label applied to anything not named and un-attached
UnattachedLabel = '- UNATTACHED - '
# Used as a temp variable to identify things without names
no_name_label = "(no name)"
# This is the prefix that automatically comes on marketplace ami-snapshots
generic_snapshot = "Created by CreateImage"


# Finds the AWS Tag:Name.value in a dict of tags
def get_tag_name(allTags):
    nameTag = None
    if allTags is not None:
        for tags in allTags:
            if tags["Key"] == 'Name':
                nameTag = tags["Value"]
    else:
        nameTag = no_name_label
        
    return nameTag


# get all the instances and their name tags to avoid multiple lookups
class instance_ids:

    def __init__(self):
        self.names = {}
        instances = list(ec2.instances.all())
        for inst in instances:
            self.names[inst.id] = get_tag_name(ec2.Instance(inst.id).tags)

    def name(self, id):
        if id in self.names:
            return(self.names[id])
        else:
            return(False)


# Iteration counter for naming passes / debugging
class counter:
        def __init__(self):
                self.number = 0
                self.total = 0

        def add(self):
                self.number += 1
                self.total += 1

        def reset(self):
                self.number = 0


# AMI rename process
def rename_amis(counter):
    log.info('[ OWNED AMI LABELING TASK STARTING ]')
    AMIFilter = {'Name': 'owner-id', 'Values': [myAWSID]}
    allAMIs = ec2.images.filter(Filters=[AMIFilter])
    for image in allAMIs:
        AMIName = image.name
        dob = image.creation_date[0:10]
        imgName = get_tag_name(image.tags)
        if imgName.startswith(no_name_label) or len(imgName) == 0:
            AMIName += f' {dob}'
            log.info(f'Labeling Image: {image.id} with {AMIName}')
            imgNewName = [{'Key': 'Name', 'Value': AMIName}]
            image.create_tags(Tags=imgNewName)
            counter.add()
        else:
            log.info(f'\t - AMI {image.id} already has a name: {imgName}')
    log.info(f'[ AMI TASK FINISHED, {counter.number} AMIS LABELED ]')
    counter.reset()


# EBS rename process
def rename_ebs_volumes(EC2IDs, counter):
    log.info('[ VOLUME RENAME TASK STARTING ]')
    for volume in ec2.volumes.all():
        volumeName = get_tag_name(volume.tags)
        if 'in-use' in volume.state:
            instID = volume.attachments[0]['InstanceId']
            instMount = volume.attachments[0]['Device']
            instName = EC2IDs.name(instID)
            newVolName = f'[ {instName} ]-{instMount}'
            volTagNewName = [{'Key': 'Name', 'Value': newVolName}]
            if volumeName is not newVolName:
                volume.create_tags(Tags=volTagNewName)
                log.info(f'\t - EBS: {volume.id} renamed {newVolName}')
                counter.add()
            else:
                log.info(f'\t - EBS {volume.id} named correctly: {newVolName}')
        if 'available' in volume.state:
            newVolName = UnattachedLabel + volumeName
            volTagNewName = [{'Key': 'Name', 'Value': newVolName}]
            if not volumeName.startswith(UnattachedLabel):
                volume.create_tags(Tags=volTagNewName)
                log.info(f'\t - EBS {volume.id} renamed: {newVolName}')
                counter.add()
            else:
                log.info(f'\t - EBS {volume.id} correctly named: {newVolName}')
    log.info(f'[ VOLUME TASK FINISHED, {counter.number} VOLUMES RENAMED ]')
    counter.reset()


# Network Interface rename process
def rename_interfaces(EC2IDs, counter):
    log.info('[ INTERFACE RENAME TASK STARTING ]')
    for interface in ec2.network_interfaces.all():
        NICNewName = '[ no attachment status ]'
        if 'in-use' in interface.status:
            if 'InstanceId' in interface.attachment:
                EC2ID = interface.attachment['InstanceId']
                if EC2ID is not None:
                    NICNewName = EC2IDs.name(EC2ID)
                else:
                    NICNewName = 'No-Instance-ID'
            else:
                try:
                    NICNewName = interface.description
                except Exception as e:
                    NICNewName = 'non-ec2-nic'
                    log.info(f'Interface isn\'t an EC2 instance: {e}')
        if 'available' in interface.status:
            NICNewName = UnattachedLabel
        NICNewNameTag = [{'Key': 'Name', 'Value': NICNewName}]
        interface.create_tags(Tags=NICNewNameTag)
        log.info(f'\t - Interface {interface.id} renamed {NICNewName}')
        counter.add()
    log.info(f'[ INTERFACE TASK FINISHED, {counter.number} NICS RENAMED ]')
    counter.reset()


# Snapshot rename process
def rename_snapshots(counter):
    log.info('[ SNAPSHOT LABELING TASK STARTING ]')
    snapFilter = {'Name': 'owner-id', 'Values': [myAWSID]}
    allSnapShots = ec2.snapshots.filter(Filters=[snapFilter])
    for snapshot in allSnapShots:
        ssid = snapshot.id
        desc = snapshot.description
        dob = snapshot.start_time.strftime("%m/%d/%y")
        snapName = get_tag_name(snapshot.tags)
        if snapName.startswith(no_name_label) or len(snapName) == 0:
            newSnapName = None
            if snapshot.description.startswith(generic_snapshot):
                if snapshot.volume_id is not None:
                    ssvid = snapshot.volume_id
                    try:
                        VolumeTags = ec2.Volume(ssvid).tags
                        newSnapName = get_tag_name(VolumeTags)
                    except Exception:
                        log.info(f'\t- NO CURRENT VOLUME WITH ID : {ssvid}')
                        newSnapName = f'Old-{ssvid}-Snapshot-{dob}'
                else:
                    newSnapName = f'CreateImage {ssvid}-Snapshot-{dob}'
            else:
                newSnapName = desc
            if newSnapName:
                log.info(f'\t- Labeling Snapashot {ssid} as {newSnapName}')
                snapNewNameTag = [{'Key': 'Name', 'Value': newSnapName}]
                snapshot.create_tags(Tags=snapNewNameTag)
                counter.add()
            else:
                log.error(f'\t- COULD NOT DETERMINE A NAME FOR: {ssid}')
        else:
            log.info(f'\t - Snapshot: {ssid} already tagged as {snapName}')
    log.info(f'[ SNAPSHOT TASK FINISHED, {counter.number} SNAPS LABELED ]')
    counter.reset()


# Main function
def lambda_handler(event, context):
    EC2Instances = instance_ids()
    renameCounter = counter()
    log.info('[ - RENAME PROGRAM STARTING - ]')
    rename_ebs_volumes(EC2Instances, renameCounter)
    rename_interfaces(EC2Instances, renameCounter)
    rename_snapshots(renameCounter)
    rename_amis(renameCounter)
    log.info(f'[ - RENAME FINSIHED, {renameCounter.total} OBJECTS RENAMED - ]')


# Run main on load if running from the command line
if __name__ == "__main__":
    lambda_handler('{}', '')

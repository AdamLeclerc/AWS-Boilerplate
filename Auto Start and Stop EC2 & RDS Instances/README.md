# AutoOrc - 1.2
## AWS Lambda based Instance **Auto-Orc**hestration
Auto start/stop AWS EC2 &amp; RDS Instances in every available region

## Usage


#### Setup
1. Create a new Lambda function
  ###### Settings:
  * Function name: ***AutoOrc*** (or whatever you'd like to call this)
  * Runtime : ***Python 3.7***
  * Handler : ***lambda_function.lambda_handler***
  * Memory : ***128 MB***
  * Timeout : ***1 Min***
  * Description : ***Auto-start/stop EC2 and RDS resources***


2. Copy the contents of '**lambda_function.py**' here to the *lambda_function.py* in the editor
3. Add these ***Environment variables*** (*keys : values*)  to the lambda:
  * **START_TAG**           : *autoOrc-up*
  * **STOP_TAG**            : *autoOrc-down*
          Change these values if you want to use different AWS tags to indicate start and stop times
  * **START_WEEKDAYS** : True|False
          Set this to True to auto-start Instances on weekends too, false will start instances on weekdays.

      (If you don't include these environment variables/forget to add them then the defaults are assumed)

4. Add tags to your EC2 and RDS (non multi-az support only) Instances that match the Environment Variables:
```python
start = 'autoOrc-up'
stop = 'autoOrc-down'
```
The values for these tags should be the **UTC time**, HH:MM you want the Instance to start and stop, e.g. ***17:30***



5. Create a CloudWatch rule (cron) that runs on a schedule of fixed rate every 1 minute, and target it to this new AutoOrc Lambda.



##### Test Events
  * To test run this Lambda, make a generic/empty test event with: \'{}\' or the default AWS console supplies.


#### IAM Permissions required for Lambda Role to execute:
  ###### (It's suggested you create a new role for this lambda, otherwise add these permissions to an existing role as needed)
  * cloudwatch:PutMetricData
  * ec2:DescribeInstances
  * ec2:DescribeInstanceStatus
  * ec2:DescribeTags
  * ec2:StartInstances
  * ec2:StopInstances
  * logs:CreateLogGroup
  * logs:CreateLogStream
  * logs:DeleteLogGroup
  * logs:DeleteLogStream
  * logs:DescribeDestinations
  * logs:DescribeLogGroups
  * logs:DescribeLogStreams
  * logs:DescribeMetricFilters
  * logs:DescribeResourcePolicies
  * logs:FilterLogEvents
  * logs:GetLogEvents
  * logs:ListTagsLogGroup
  * logs:PutLogEvents
  * logs:TagLogGroup
  * rds:DescribeDBInstances
  * rds:ListTagsForResource
  * rds:StartDBInstance
  * rds:StopDBInstance
  * sts:GetCallerIdentity

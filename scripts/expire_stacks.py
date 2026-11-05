"""Print JSON list of demo_ids whose ExpiresOn tag is in the past (used by the nightly workflow)."""
import datetime as dt
import json

import boto3

import argparse

p = argparse.ArgumentParser()
p.add_argument("--region", required=True)
p.add_argument("--profile")
a = p.parse_args()
client = boto3.Session(profile_name=a.profile, region_name=a.region).client("resourcegroupstaggingapi")
today = dt.date.today().isoformat()
expired = set()
for page in client.get_paginator("get_resources").paginate(TagFilters=[{"Key": "Project", "Values": ["s3-demo"]},
                                                                      {"Key": "Scenario", "Values": ["scenario-2"]}]):
    for r in page["ResourceTagMappingList"]:
        t = {x["Key"]: x["Value"] for x in r["Tags"]}
        if t.get("DemoId") and t.get("ExpiresOn", "9999") < today:
            expired.add(t["DemoId"])
print(json.dumps(sorted(expired)))

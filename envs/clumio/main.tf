# Protection group: selects the demo bucket by tag and excludes the log prefix(es) from backup.
resource "clumio_protection_group" "demo" {
  name        = "s3demo-${var.demo_id}-no-logs"
  description = "Demo: backs up s3demo-${var.demo_id}-data except ${join(", ", var.excluded_prefixes)}"

  bucket_rule = jsonencode({
    aws_tag = {
      "$eq" = {
        key   = "DemoId"
        value = var.demo_id
      }
    }
  })

  object_filter {
    latest_version_only = false
    storage_classes     = var.storage_classes

    prefix_filters {
      prefix                = ""                    # whole bucket ...
      excluded_sub_prefixes = var.excluded_prefixes # ... minus these
    }
  }
}

# Policy: continuous backup needs BOTH operations (a periodic one plus the continuous one).
resource "clumio_policy" "demo" {
  name = "s3demo-${var.demo_id}-continuous"

  operations {
    action_setting = "immediate"
    type           = "protection_group_backup"

    slas {
      retention_duration {
        unit  = "days"
        value = var.retention_days
      }
      rpo_frequency {
        unit  = "days"
        value = 1
      }
    }

    advanced_settings {
      protection_group_backup {
        backup_tier = "cold"
      }
    }
  }

  operations {
    action_setting = "immediate"
    type           = "aws_s3_continuous_backup"

    slas {
      retention_duration {
        unit  = "days"
        value = var.retention_days
      }
      rpo_frequency {
        unit  = "minutes"
        value = var.continuous_rpo_minutes
      }
    }

    advanced_settings {
      protection_group_continuous_backup {
        # AWS Backup continuous mode on the same bucket also needs EventBridge notifications,
        # so never let Clumio switch them off on teardown.
        disable_eventbridge_notification = false
      }
    }
  }
}

resource "clumio_policy_assignment" "demo" {
  entity_id   = clumio_protection_group.demo.id
  entity_type = "protection_group"
  policy_id   = clumio_policy.demo.id
}

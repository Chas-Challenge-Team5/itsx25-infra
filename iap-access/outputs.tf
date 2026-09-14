output "iap_access" {
  description = "Target and scope of the access grants; does not confirm successful SSH login testing"
  value = {
    project   = var.project_id
    zone      = var.zone
    instance  = var.instance_name
    ip        = var.destination_ip
    port      = 22
    condition = local.iap_condition
    users     = sort(tolist(var.iap_users))
  }
}

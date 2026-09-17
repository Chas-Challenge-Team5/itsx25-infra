variable "headscale_proxy_cidr" {
  description = "Single IPv4 address of Spectre, the instructor's Headscale reverse proxy, expressed as a /32 CIDR. Also the destination of the tailnet route and masquerade rule (#51)."
  type        = string
  default     = "10.0.0.2/32"

  validation {
    condition     = can(cidrnetmask(var.headscale_proxy_cidr)) && can(regex("/32$", var.headscale_proxy_cidr))
    error_message = "headscale_proxy_cidr must be a valid IPv4 /32 CIDR."
  }
}

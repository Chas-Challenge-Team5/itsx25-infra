terraform {
  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/state"
  }
}

# Audit-loggar för SSH och OS Login

Detta dokument beskriver hur vi spårar vem som loggat in på **jumphost** och **primary**, vilket filter som används och hur loggraderna ska tolkas.

---

## Filter för Cloud Logging

I GCP Log Explorer använder vi följande filter för att fånga anropen när användare ansluter via OS Login:

```text
protoPayload.methodName="google.cloud.oslogin.v1.OsLoginService.ListLoginProfiles"
```
Koden ser ut så här=
```text
gcloud logging read 'protoPayload.serviceName="oslogin.googleapis.com" protoPayload.methodName=~"CheckPolicy" protoPayload.request.policy="LOGIN" protoPayload.request.instance=~"team5-(jumphost|primary)"' \
  --format="table(timestamp, protoPayload.authenticationInfo.principalEmail:label=USER, protoPayload.request.instance:label=INSTANCE)" \
  --freshness=7d --limit=50
```

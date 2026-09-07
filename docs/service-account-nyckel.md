# Sektion 6: CI/CD-nyckeln

Team 5. Kontot `team5-cicd` har `roles/editor` på hela `itsx25-lab`. I bootstrap skapades en statisk nyckel som hamnade i klartext i staten och i GitHub-secreten `GCP_SA_KEY`. Vi har bytt autentiseringen till WIF. Här är varför den gamla nyckeln måste bort.

## hur den kan användas utanför pipelinen

Nyckeln ÄR kontot. Den som har JSON-filen kör `gcloud auth activate-service-account --key-file=key.json` på sin egen laptop och är `team5-cicd`. Var som helst, ingen MFA, ingen IP-spärr, inget utgångsdatum. GCP kan inte se skillnad på vår Actions-körning och en angripares maskin, för det finns ingen skillnad. Innehav är åtkomst.

Och den låg redan illa till. Staten låg i en bucket som en period var läsbar för alla inloggade Google-konton. Det var precis så vi tog flagga 1: hittade staten, avkodade base64, läste nyckeln. Kunde vi det kunde vem som helst det.

En WIF-token lever i minuter och mintas bara för vårt repo. En stulen nyckel gäller tills någon manuellt återkallar den.

## vad en angripare skulle göra med den

Editor på hela projektet, så nästan allt utom att röra IAM.

Samma trick som vi: dra nyckeln ur staten, aktivera den, kör `gcloud compute instances list`. Nu ser angriparen nätverket. Editor räcker för att skapa en egen instans med publik IP inne i vårt VPC, och då sitter hen på insidan av det jumphosten skulle skydda.

Eller enklare: starta dyra instanser och mina krypto tills fakturan är tömd. Eller läsa varenda bucket och Secret Manager och exfiltrera allt. Eller radera jumphosten och staten.

Editor kan inte höja sig till owner. Men blast-radien är redan hela projektet, så det spelar mindre roll.

## hur vi inaktiverar den, och varför

Vi tar bort `google_service_account_key.cicd` ur bootstrap och kör apply, då raderas nyckeln i GCP. Vi tar också bort secreten `GCP_SA_KEY`.

Varför bry sig när man "bara" kan ta bort den? För att så länge den finns är den en levande inloggning som kan läcka. Bucketen har versionshantering, så nyckeln kan ligga kvar i äldre stateversioner även efter att vi redigerat bort resursen. Det är återkallandet i GCP som faktiskt dödar den, inte att vi städar i en fil. Och med WIF behöver vi ingen statisk nyckel alls. Att låta den ligga kvar är rent nedsida.

Ordningen spelar roll. Nyckeln bort först efter en grön deploy via WIF, annars låser vi ut vår egen pipeline.

## vad vi missat

`roles/editor` är för brett, och WIF fixar inte det. WIF stänger stölden av inloggningen. Den krymper inte vad inloggningen får göra. En kapad körning antar fortfarande editor. Least privilege behövs oavsett (#10).

Gamla stateversioner lever kvar. Att redigera bort resursen räcker inte, återkallandet i GCP är det riktiga.

Actions är pinnade på flyttbara taggar (#13). En kapad tagg kan läsa ut både token och nyckel mitt i en körning. Pinna på SHA.

Bootstrap körs utanför CI med en människas inloggning (#9), och det saknas rader i bootstrap jämfört med `wif.patch` (#8).

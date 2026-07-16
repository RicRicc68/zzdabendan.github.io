# Proxy Spagna su AWS (eu-south-2) per il bot Polymarket

Serve a far coincidere l'IP con cui il bot chiama le API di Polymarket con
la tua reale residenza in Spagna, dato che Render non ha una region li'
(vedi discussione nel repo / config.py per il contesto).

## 1. Setup account (manuale, una tantum)

1. Crea un account su https://aws.amazon.com/ (email, carta di pagamento,
   verifica telefonica: passaggi loro, non automatizzabili).
2. Accedi alla console -> in alto a destra, nome account -> **Account** ->
   sezione **AWS Regions** -> trova "Spain (eu-south-2)" -> **Enable**.
   Puo' richiedere da pochi minuti a un paio d'ore per propagare.
3. Crea un utente IAM per l'uso da CLI (evita di usare le chiavi root):
   IAM -> Users -> Create user -> Attach policy `AmazonEC2FullAccess`
   (o una policy piu' ristretta se preferisci) -> Security credentials ->
   Create access key.
4. In locale: `aws configure` e incolla Access Key ID / Secret / region
   default `eu-south-2`.

## 2. Provisioning

```bash
cd deploy/aws_spain_proxy
./setup.sh
```

Lo script:
- rileva il tuo IP per limitare l'accesso SSH a te soltanto,
- crea key pair + security group (SSH solo da te, porta proxy 3128 aperta
  ma protetta da utente/password Squid),
- lancia una `t3.micro` (rientra nel free tier AWS il primo anno) con
  Amazon Linux 2023,
- installa e configura Squid con autenticazione tramite cloud-init,
- stampa in output il `PROXY_URL` completo di credenziali.

## 3. Collegalo al bot

Copia il `PROXY_URL` stampato alla fine e impostalo come env var
`PROXY_URL` nel servizio Render (Dashboard -> il servizio -> Environment).
Redeploy: il bot instradera' le chiamate al CLOB tramite il proxy
(vedi `config.py`).

## 4. Costi / cleanup

Una `t3.micro` accesa 24/7 e' pochi dollari al mese fuori free tier.
Per terminarla quando non serve piu':

```bash
aws ec2 terminate-instances --region eu-south-2 --instance-ids <INSTANCE_ID>
```

"""
Polymarket Copy Trade Bot
Monitora wallet 0x15ceffed7bf820cd2d90f90ea24ae9909f5cd5fa su Polygon
e replica automaticamente le posizioni su Polymarket.

REQUISITI:
  pip install web3 requests python-dotenv websockets asyncio

SETUP:
  1. Crea un file .env con:
     PRIVATE_KEY=la_tua_chiave_privata
     ALCHEMY_API_KEY=la_tua_api_key  (da alchemy.com - free tier)
     YOUR_WALLET=il_tuo_indirizzo_wallet
  2. Assicurati di avere pUSD su Polygon nel tuo wallet
  3. python polymarket_copytrade.py
"""

import os
import asyncio
import json
import time
import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from dotenv import load_dotenv

load_dotenv(dotenv_path='/mnt/c/poly/.env')

# ─── CONFIG ───────────────────────────────────────────────
TARGET_WALLET     = "0x15ceffed7bf820cd2d90f90ea24ae9909f5cd5fa"

def to_checksum_address(addr: str | None) -> str | None:
    return Web3.to_checksum_address(addr) if addr else None

YOUR_WALLET       = to_checksum_address(os.getenv("YOUR_WALLET"))
PRIVATE_KEY       = os.getenv("PRIVATE_KEY")
ALCHEMY_API_KEY   = os.getenv("ALCHEMY_API_KEY")

# Scala del copy trade (es. 0.5 = copia il 50% dell'importo originale)
COPY_RATIO        = 0.5

# Importo massimo per singola operazione (in pUSD, 6 decimali)
MAX_TRADE_USDC    = 50  # $50 max per trade

# Polygon RPC
POLYGON_RPC       = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
print('DEBUG: cwd=', os.getcwd())
print('DEBUG: ALCHEMY_API_KEY=', ALCHEMY_API_KEY)
print('DEBUG: POLYGON_RPC=', POLYGON_RPC)

# Polymarket CTF Exchange (contratto principale su Polygon)
POLYMARKET_CTF    = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")

# pUSD su Polygon (Polymarket stablecoin)
PUSD_ADDRESS      = Web3.to_checksum_address("0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb")
PUSD_DECIMALS     = 6

# ─── ABI MINIMALE CTF EXCHANGE ────────────────────────────
CTF_ABI = [
    {
        "name": "buyShares",
        "type": "function",
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "outcomeIndex", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "minShares", "type": "uint256"}
        ],
        "outputs": [{"name": "", "type": "uint256"}]
    },
    {
        "name": "splitPosition",
        "type": "function",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "partition", "type": "uint256[]"},
            {"name": "amount", "type": "uint256"}
        ],
        "outputs": []
    }
]

USDC_ABI = [
    {
        "name": "approve",
        "type": "function",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "outputs": [{"name": "", "type": "bool"}]
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}]
    }
]

# ─── INIT WEB3 ────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

if not w3.is_connected():
    print("❌ Connessione a Polygon fallita. Controlla la tua ALCHEMY_API_KEY.")
    exit(1)

print(f"✅ Connesso a Polygon — Block: {w3.eth.block_number}")

ctf_contract  = w3.eth.contract(address=POLYMARKET_CTF, abi=CTF_ABI)
pusd_contract = w3.eth.contract(address=PUSD_ADDRESS, abi=USDC_ABI)

# ─── UTILITY ──────────────────────────────────────────────

def get_usdc_balance(wallet: str) -> float:
    raw = pusd_contract.functions.balanceOf(wallet).call()
    return raw / (10 ** PUSD_DECIMALS)

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def get_matic_balance(wallet: str) -> float:
    raw = w3.eth.get_balance(wallet)
    return raw / 10**18

def get_nonzero_default_token_count(wallet: str) -> int:
    if not ALCHEMY_API_KEY:
        return -1

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getTokenBalances",
        "params": [wallet, "DEFAULT_TOKENS"]
    }
    try:
        resp = requests.post(POLYGON_RPC, json=payload, timeout=10)
        data = resp.json()
        tokens = data.get("result", {}).get("tokenBalances", [])
        return sum(1 for t in tokens if int(t.get("tokenBalance", "0"), 16) > 0)
    except Exception:
        return -1


def print_diagnostics():
    log("🔧 Diagnostics:")
    log(f"   YOUR_WALLET: {YOUR_WALLET}")
    log(f"   ALCHEMY_API_KEY: {'set' if ALCHEMY_API_KEY else 'missing'}")
    log(f"   PRIVATE_KEY: {'set' if PRIVATE_KEY else 'missing'}")

    if w3.is_connected():
        log(f"   Polygon connected at block {w3.eth.block_number}")
        log(f"   pUSD balance: ${get_usdc_balance(YOUR_WALLET):.6f}")
        log(f"   MATIC balance: {get_matic_balance(YOUR_WALLET):.6f}")
        token_count = get_nonzero_default_token_count(YOUR_WALLET)
        if token_count >= 0:
            log(f"   Nonzero default tokens: {token_count}")
        else:
            log("   Nonzero default token check failed")
    else:
        log("   Polygon RPC not connected")


def write_stats(status="running", balance=0.0, trades=0, equity_curve=[], initial_balance=10.0):
    # Calculate metrics for dashboard
    current_equity = balance if balance > 0 else initial_balance
    total_return = ((current_equity - initial_balance) / initial_balance * 100) if initial_balance > 0 else 0.0
    
    stats = {
        "status": status,
        "timestamp": int(time.time() * 1000),
        "wallet_address": YOUR_WALLET,
        "portfolio": {
            "wallet_balance": balance,
            "total_equity": current_equity,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "total_return_percent": total_return,
            "drawdown_percent": 0.0,
            "active_positions": 0,
            "total_positions_value": 0.0
        },
        "trading": {
            "total_trades": trades,
            "winning_positions": 0,
            "losing_positions": 0,
            "win_rate": 0.0,
            "avg_win_loss": 0.0
        },
        "equity_curve": equity_curve
    }
    with open("copytrade_stats.json", "w") as f:
        json.dump(stats, f)

# ─── DECODIFICA TRANSAZIONE POLYMARKET ────────────────────

def decode_polymarket_tx(tx) -> dict | None:
    """
    Decodifica una transazione verso il contratto CTF Exchange.
    Restituisce i parametri della scommessa o None se non riconosciuta.
    """
    try:
        input_data = tx.input
        if not input_data or input_data == "0x":
            return None

        # Selector buyShares: 0x... (dipende dall'ABI)
        # Proviamo a decodificare con l'ABI
        func, args = ctf_contract.decode_function_input(input_data)
        return {
            "function": func.fn_name,
            "args": args,
            "value": tx.value
        }
    except Exception:
        return None

# ─── ESECUZIONE COPY TRADE ────────────────────────────────

def execute_copy_trade(decoded_tx: dict):
    """
    Replica la transazione sul tuo wallet, scalata per COPY_RATIO.
    """
    if not YOUR_WALLET or not PRIVATE_KEY:
        log("❌ YOUR_WALLET o PRIVATE_KEY mancanti nel file .env")
        return

    balance = get_usdc_balance(YOUR_WALLET)
    log(f"💰 Il tuo saldo pUSD: ${balance:.2f}")

    fn_name = decoded_tx.get("function", "")
    args    = decoded_tx.get("args", {})

    if fn_name == "buyShares":
        original_amount = args.get("amount", 0) / (10 ** USDC_DECIMALS)
        copy_amount     = min(original_amount * COPY_RATIO, MAX_TRADE_USDC)

        if copy_amount > balance:
            log(f"⚠️  Saldo insufficiente. Serve ${copy_amount:.2f}, hai ${balance:.2f}")
            return

        log(f"📋 Originale: ${original_amount:.2f} USDC → Copia: ${copy_amount:.2f} USDC")
        log(f"   Market conditionId: {args.get('conditionId', '?').hex()}")
        log(f"   Outcome: {args.get('outcomeIndex', '?')}")

        amount_raw = int(copy_amount * (10 ** USDC_DECIMALS))

        # 1. Approva pUSD
        nonce = w3.eth.get_transaction_count(YOUR_WALLET)
        approve_tx = pusd_contract.functions.approve(
            POLYMARKET_CTF, amount_raw
        ).build_transaction({
            "from":     YOUR_WALLET,
            "nonce":    nonce,
            "gas":      100_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        approve_hash   = w3.eth.send_raw_transaction(signed_approve.rawTransaction)
        log(f"✅ Approve pUSD inviato: {approve_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(approve_hash)

        # 2. Esegui buyShares
        nonce += 1
        buy_tx = ctf_contract.functions.buyShares(
            args["conditionId"],
            args["outcomeIndex"],
            amount_raw,
            0  # minShares = 0 (nessun slippage guard, gestisci con attenzione)
        ).build_transaction({
            "from":     YOUR_WALLET,
            "nonce":    nonce,
            "gas":      300_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed_buy = w3.eth.account.sign_transaction(buy_tx, PRIVATE_KEY)
        buy_hash   = w3.eth.send_raw_transaction(signed_buy.rawTransaction)
        log(f"🚀 Trade eseguito! TX: https://polygonscan.com/tx/{buy_hash.hex()}")
    else:
        log(f"ℹ️  Funzione '{fn_name}' non gestita — skip.")

# ─── MONITORAGGIO BLOCCHI ─────────────────────────────────

async def monitor_wallet():
    log(f"👁️  Monitoraggio wallet: {TARGET_WALLET}")
    log(f"   Copy ratio: {COPY_RATIO*100:.0f}% | Max per trade: ${MAX_TRADE_USDC}")
    log("─" * 60)

    trades_count = 0
    initial_balance = get_usdc_balance(YOUR_WALLET)
    equity_curve = [initial_balance]
    write_stats(balance=initial_balance, trades=trades_count, equity_curve=equity_curve, initial_balance=initial_balance)

    last_block = w3.eth.block_number
    log(f"   Partenza dal blocco: {last_block}")

    while True:
        try:
            current_block = w3.eth.block_number

            if current_block > last_block:
                for block_num in range(last_block + 1, current_block + 1):
                    block = w3.eth.get_block(block_num, full_transactions=True)

                    for tx in block.transactions:
                        # Filtra transazioni dal wallet target verso Polymarket
                        if (tx["from"].lower() == TARGET_WALLET.lower() and
                                tx["to"] and
                                tx["to"].lower() == POLYMARKET_CTF.lower()):

                            log(f"🎯 TX rilevata dal target! Block {block_num}")
                            log(f"   Hash: {tx['hash'].hex()}")

                            decoded = decode_polymarket_tx(tx)
                            if decoded:
                                log(f"   Funzione: {decoded['function']}")
                                execute_copy_trade(decoded)
                                trades_count += 1
                                new_balance = get_usdc_balance(YOUR_WALLET)
                                equity_curve.append(new_balance)
                            else:
                                log("   ⚠️  Impossibile decodificare la TX")

                last_block = current_block

            write_stats(balance=get_usdc_balance(YOUR_WALLET), trades=trades_count, equity_curve=equity_curve, initial_balance=initial_balance)
            await asyncio.sleep(2)  # Polling ogni 2 secondi (1 blocco Polygon ~2s)

        except KeyboardInterrupt:
            log("🛑 Bot fermato dall'utente.")
            write_stats(status="stopped", balance=get_usdc_balance(YOUR_WALLET), trades=trades_count, equity_curve=equity_curve, initial_balance=initial_balance)
            break
        except Exception as e:
            log(f"❌ Errore: {e}")
            await asyncio.sleep(5)

# ─── MAIN ─────────────────────────────────────────────────

if __name__ == "__main__":
    if not ALCHEMY_API_KEY:
        print("❌ Manca ALCHEMY_API_KEY nel file .env")
        exit(1)

    print_diagnostics()
    balance = get_usdc_balance(YOUR_WALLET or "0x0000000000000000000000000000000000000000")
    log(f"💼 Wallet: {YOUR_WALLET}")
    log(f"💰 Saldo pUSD: ${balance:.2f}")

    write_stats(balance=balance, trades=0, equity_curve=[balance], initial_balance=balance)
    asyncio.run(monitor_wallet())

from web3 import Web3

print("Test 1: Public Polygon RPC...")
try:
    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
    result = w3.is_connected()
    print(f"  Connected: {result}")
    if result:
        print(f"  Block: {w3.eth.block_number}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

print("\nTest 2: Alchemy with new key...")
api_key = "YHrZPjEsUSHEZnTmSVv8F"
try:
    url = f"https://polygon-mainnet.g.alchemy.com/v2/{api_key}"
    w3 = Web3(Web3.HTTPProvider(url))
    result = w3.is_connected()
    print(f"  Connected: {result}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

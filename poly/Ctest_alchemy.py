import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

alchemy_key = os.getenv('ALCHEMY_API_KEY')
print(f'Alchemy Key (first 10 chars): {alchemy_key[:10] if alchemy_key else "NOT SET"}')

# Try with public Polygon RPC first
print('\nTrying public Polygon RPC (polygon-rpc.com)...')
try:
    w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
    connected = w3.is_connected()
    print(f'Connected: {connected}')
    if connected:
        block = w3.eth.block_number
        print(f'Latest block: {block}')
except Exception as e:
    print(f'Error: {e}')

# Try with new Alchemy key
print(f'\nTrying Alchemy endpoint with new key...')
if alchemy_key:
    try:
        url = f'https://polygon-mainnet.g.alchemy.com/v2/{alchemy_key}'
        w3 = Web3(Web3.HTTPProvider(url))
        connected = w3.is_connected()
        print(f'Connected: {connected}')
    except Exception as e:
        print(f'Error: {e}')
else:
    print('Alchemy key not found in .env')

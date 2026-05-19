import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()
print('ALCHEMY_API_KEY=', os.getenv('ALCHEMY_API_KEY'))
print('YOUR_WALLET=', os.getenv('YOUR_WALLET'))
print('PRIVATE_KEY=', os.getenv('PRIVATE_KEY')[:10] if os.getenv('PRIVATE_KEY') else None)
url = f"https://polygon-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_API_KEY')}"
print('RPC URL=', url)
try:
    w3 = Web3(Web3.HTTPProvider(url))
    print('is_connected=', w3.is_connected())
    if w3.is_connected():
        print('block=', w3.eth.block_number)
except Exception as e:
    print('Exception:', type(e).__name__, e)

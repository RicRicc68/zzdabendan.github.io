from web3 import Web3
w = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
print(type(w.middleware_onion))
print([a for a in dir(w.middleware_onion) if not a.startswith('_')])

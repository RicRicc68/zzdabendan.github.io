import os
import runpy
os.chdir(r'C:\poly')
print('WORKDIR', os.getcwd())
runpy.run_path(r'C:\polymarket_copytrade.py', run_name='__main__')

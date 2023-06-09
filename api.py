from fastapi import FastAPI, Request, Depends, APIRouter, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from copy import deepcopy
import os
import socket
import json
import uvicorn
import argparse
import pickle
import time
import threading
import requests

from node import Node
from transaction import Transaction
from utxo import UTXO
from blockchain import Blockchain

app = FastAPI()
# app = APIRouter()

# CORS (Cross-Origin Resource Sharing)
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

################## ARGUMENTS #####################
argParser = argparse.ArgumentParser()
argParser.add_argument("-p", "--port", help="Port in which node is running", default=8000, type=int)
argParser.add_argument("--ip", help="IP of the host")
args = argParser.parse_args()

################## HELPER FUNCTIONS #####################
def create_genesis_block():
    """
    ! BOOTSTRAP ONLY !
    Create the first block of the blockchain (GENESIS BLOCK)
    """
    # 1. Create new block
    gen_block = node.create_new_block() # previous_hash autogenerates
    gen_block.nonce = 0

    # 2. Create first transaction
    first_transaction = Transaction(
        sender_address='0', 
        sender_private_key=None, 
        receiver_address = node.wallet.address, 
        value = total_nbc
    )

    # 3. Add transaction to genesis block
    gen_block.transactions_list.append(first_transaction)
    gen_block.calculate_hash() # void

    # 4. Add genesis block to bockchain
    node.blockchain.chain.append(gen_block)

    # 5. Add first UTXO
    node.blockchain.UTXOs[0].append(UTXO(-1, node.id, total_nbc))

    # 6. Create new empty block
    node.current_block = node.create_new_block()
    
    return

################## INITIALIZATION #####################
# Step 1. 
# Initialize the new node
node = Node()

# Step 2.
# Get info about the cluster, bootstrap node
load_dotenv()
total_nodes = int(os.getenv('TOTAL_NODES'))
total_nbc = total_nodes * 100

bootstrap_node = {
    'ip': os.getenv('BOOTSTRAP_IP'),
    'port': os.getenv('BOOTSTRAP_PORT')
}

# Step 3.
# Set the IP and PORT
# DOCKER SPECIFIC
ip_address = args.ip
# IP ADDRESS
if (ip_address is None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip_address = s.getsockname()[0]
    s.close()
print('IP address: ', ip_address) # debug
# PORT
port = args.port
print('PORT: ', port) # debug
node.ip = ip_address
node.port = str(port)

# Step 4. 
# See if node is Bootstrap node
if (ip_address == bootstrap_node["ip"] and str(port) == bootstrap_node["port"]):
    node.is_bootstrap = True
    print("I am bootstrap")

# Step 5.
# Register node to the cluster
if (node.is_bootstrap):
    # Add himself to ring
    node.id = 0
    node.add_node_to_ring(node.id, node.ip, node.port, node.wallet.address, total_nbc)
    create_genesis_block()

else:
    node.unicast_node(bootstrap_node)

################## CLIENT ROUTES #####################

@app.get("/api/create_transaction/{receiver_id}/{amount}")
def create_transaction(receiver_id: int, amount: int):
    """
    Creates a new transaction given a receiver wallet and an amount
    """
    if (receiver_id >= total_nodes):
        return JSONResponse({"message":'Node ID does not exist'}, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Check if there are enough NBCs
    # !! Only for cli demo
    # if (node.ring[node.wallet.address]['balance'] < amount):
    #     return JSONResponse(content={"message":'Not enough Noobcoins in wallet'}, status_code=status.HTTP_400_BAD_REQUEST)
    
    # 1. Create transaction
    receiver_address = list(node.ring.keys())[receiver_id]
    transaction = node.create_transaction(receiver_address, amount)
    # 3. Add to pending transactions list
    node.add_transaction_to_pending(transaction)
    # 4. Broadcast transaction
    node.broadcast_transaction(transaction)

    return JSONResponse('Successful Transaction !', status_code=status.HTTP_200_OK)

@app.get("/api/view_transactions")
def view_transactions():
    """
    Returns the transactions of the last validated, mined block
    """
    if (len(node.blockchain.chain) <= 1):
        return JSONResponse('There are no mined blocks at the moment !')
    
    # 1. Get last block in the chain
    latest_block = node.blockchain.chain[-1]
    # 2. Return a list of transactions (sender, receiver, amount)
    transactions = []
    for transaction in latest_block.transactions_list:
        transactions.append(
            {
                "sender_id": node.ring[transaction.sender_address]['id'],
                # "sender_address": transaction.sender_address,
                "receiver_id": node.ring[transaction.receiver_address]['id'],
                # "receiver_address": transaction.receiver_address,
                "amount": transaction.amount
            }
        )

    return JSONResponse(transactions, status_code=status.HTTP_200_OK)

@app.get("/api/get_balance")
def get_balance():
    """
    Gets the total balance for the given node (in NBCs)
    """
    # 1. Get the NBCs attribute from the node object
    balance = node.ring[node.wallet.address]['balance'] # Alternative
    # balance = node.blockchain.wallet_balance(node.id)

    return JSONResponse({'balance': balance}, status_code=status.HTTP_200_OK)

@app.get("/api/get_chain_length")
def get_chain_length():
    """
    Gets the current valid blockchain length of the receiver
    """
    # 1. Get the current length of the node's blockchain
    chain_len = len(node.blockchain.chain)

    return JSONResponse({'chain_length': chain_len}, status_code=status.HTTP_200_OK)

@app.get("/api/get_chain")
def get_chain():
    """
    Gets the current valid blockchain of the receiver
    """
    # 1. Get the current length of the node's blockchain
    return Response(pickle.dumps(node.blockchain), status_code=status.HTTP_200_OK)

################## INTERNAL ROUTES #####################
@app.get("/")
async def root():
    # return {"message": f"Welcome to Noobcoin. I am {socket.gethostname()} : {socket.gethostbyname(socket.gethostname())}"}
    return {"message": f"Welcome to Noobcoin"}

@app.post("/get_ring")
async def get_ring(request: Request):
    """
    Gets the completed list of nodes from Bootstrap node
    """
    data = await request.body()
    node.ring = pickle.loads(data)

    print("Ring received successfully !")
    return JSONResponse('OK')

@app.post("/get_blockchain")
async def get_blockchain(request: Request):
    """
    Gets the lastest version of the blockchain from the Bootstrap node
    """
    data = await request.body()
    node.blockchain = pickle.loads(data)
    node.temp_utxos = deepcopy(node.blockchain.UTXOs)

    print("Blockchain received successfully !")
    return JSONResponse('OK')

async def get_body(request: Request):
    return await request.body()

@app.post("/get_transaction")
def get_transaction(data: bytes = Depends(get_body)):
    """
    Gets an incoming transaction and adds it in the block.
    """
    # data = request.body()
    new_transaction = pickle.loads(data)
    print("New transaction received successfully !")

    # Add transaction to block
    node.add_transaction_to_pending(new_transaction)

    return JSONResponse('OK')

@app.post("/get_block")
def get_block(data: bytes = Depends(get_body)):
    """
    Gets an incoming mined block and adds it to the blockchain.
    """
    # data = request.body()
    new_block = pickle.loads(data)
    print("New block received successfully !")

    # Wait until incoming block has finished processing
    with (node.processing_block_lock):
        # 1. Check validity of block
        if (new_block.validate_block(node.blockchain)):
            # If it is valid:
            # 1. Stop the current block mining
            with(node.incoming_block_lock):
                node.incoming_block = True
            # node.processing_block = False
            print("Block was ⛏️  by someone else 🧑")
            # 2. Add block to the blockchain
            print("✅📦! Adding it to the chain")
            node.add_block_to_chain(new_block)
            print("Blockchain length: ", len(node.blockchain.chain))
        
        # Check if latest_block.previous_hash == incoming_block.previous_hash
        elif(node.blockchain.chain[-1].previous_hash == new_block.previous_hash):
            print("🗑️  Rejected incoming block")
        else:
            print("Incoming block previous_hash: ", new_block.previous_hash)
            print("🔗 BLOCKCHAIN 🔗")
            print([block.hash[:7] for block in node.blockchain.chain])
            # Resolve conflict in case of wrong previous_hash
            node.blockchain.resolve_conflict(node)
            print("❌📦 Something went wrong with validation 🙁")

        return JSONResponse('OK')

@app.post("/let_me_in")
async def let_me_in(request: Request):
    #https://i.imgflip.com/2u5y6a.png?a466200
    """
    ! BOOTSTRAP ONLY !
    Adds a new node to the cluster
    """
    # Get the parameters
    data = await request.form()
    ip = data.get('ip')
    port = data.get('port')
    address = data.get('address')
    id = len(node.ring)

    # Add node to the ring
    node.add_node_to_ring(id, ip, port, address, 0)

    # Check if all nodes have joined 
    # !! (do it after you have responded to the last node)
    t = threading.Thread(target=check_full_ring)
    t.start()

    return JSONResponse({'id': id})

def check_full_ring():
    """
    ! BOOTSTRAP ONLY !
    Checks if all nodes have been added to the ring
    """
    time.sleep(1)
    if (len(node.ring) == total_nodes):
        node.broadcast_ring()
        node.broadcast_blockchain()
        node.broadcast_initial_nbc()
        
################## WEBSERVER #####################
uvicorn.run(app, host="0.0.0.0", port=port)
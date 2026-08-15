import os

from web3 import Web3

RPC_URL = os.getenv("LEGALVAULT_RPC_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS = os.getenv(
    "LEGALVAULT_CONTRACT_ADDRESS",
    "0x5FbDB2315678afecb367f032d93F642f64180aa3",
)
PRIVATE_KEY = os.getenv("LEGALVAULT_PRIVATE_KEY")

LEGAL_VAULT_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "_documentId", "type": "string"},
            {"internalType": "string", "name": "_documentHash", "type": "string"},
            {"internalType": "uint256", "name": "_version", "type": "uint256"},
        ],
        "name": "registerDocument",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "_documentId", "type": "string"}],
        "name": "getDocument",
        "outputs": [
            {"internalType": "string", "name": "", "type": "string"},
            {"internalType": "string", "name": "", "type": "string"},
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
            {"internalType": "uint256", "name": "", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def register_document_on_chain(document_id: str, document_hash: str, version: int) -> dict:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise ConnectionError(f"Unable to connect to Ethereum node at {RPC_URL}")

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=LEGAL_VAULT_ABI,
    )

    if PRIVATE_KEY:
        account = w3.eth.account.from_key(PRIVATE_KEY)
        sender = account.address
    else:
        sender = w3.eth.accounts[0]

    nonce = w3.eth.get_transaction_count(sender)
    transaction = contract.functions.registerDocument(
        document_id,
        document_hash,
        version,
    ).build_transaction(
        {
            "from": sender,
            "nonce": nonce,
            "gas": 500_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        }
    )

    if PRIVATE_KEY:
        signed_tx = account.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    else:
        tx_hash = w3.eth.send_transaction(transaction)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    status = "confirmed" if receipt.status == 1 else "failed"
    return {
        "blockchain_tx_hash": tx_hash.hex(),
        "blockchain_status": status,
    }

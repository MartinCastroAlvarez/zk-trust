import json
import logging
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime
import begin

import requests
from web3 import Web3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ETHERSCAN_API_URL = "https://api.etherscan.io/api"
COINMARKETCAP_API_URL = "https://pro-api.coinmarketcap.com/"


@dataclass
class Proof:
    a: list[int]
    b: list[list[int]]
    c: list[int]

    def to_solidity(self) -> tuple[tuple[int, int], list[list[int]], tuple[int, int]]:
        return (
            (int(self.a[0], 16), int(self.a[1], 16)),  # a: (uint256, uint256)
            [
                [int(self.b[0][0], 16), int(self.b[0][1], 16)],  # b[0]: (uint256[2])
                [int(self.b[1][0], 16), int(self.b[1][1], 16)],  # b[1]: (uint256[2])
            ],
            (int(self.c[0], 16), int(self.c[1], 16)),  # c: (uint256, uint256)
        )


@dataclass
class Inputs:
    score: int
    signature: int
    address_part1: int
    address_part2: int

    def to_solidity(self) -> list[int]:
        return [
            self.score,
            self.signature,
            self.address_part1,
            self.address_part2,
        ]

    def get_normalized_score(self) -> float:
        BN128_PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
        return self.score / BN128_PRIME  # Approximate floating-point representation


@dataclass
class Computation:
    curve: str
    proof: Proof
    scheme: str
    inputs: Inputs


@dataclass
class Stats:
    contract_address: str
    has_source_code: bool
    total_supply: int
    name: str
    symbol: str
    days_ago_added: int
    is_active: bool
    volume: int
    market_cap: int

    def to_dict(self) -> dict:
        return {
            "contract_address": self.contract_address,
            "has_source_code": self.has_source_code,
            "total_supply": self.total_supply,
            "name": self.name,
            "symbol": self.symbol,
            "days_ago_added": self.days_ago_added,
            "is_active": self.is_active,
            "volume": self.volume,
            "market_cap": self.market_cap,
        }

    def split_address(self) -> tuple[int, int]:
        """
        You may do this in Solidity:

        function splitAddress(address _addr) public pure returns (uint128, uint128) {
            uint160 addrInt = uint160(_addr); // Convert address to uint160
            // Extract first 80 bits (upper half)
            uint128 addressPart1 = uint128(addrInt >> 80);
            // Extract last 80 bits (lower half)
            uint128 addressPart2 = uint128(addrInt & ((1 << 80) - 1));
            return (addressPart1, addressPart2);
        }
        """
        size = len(self.contract_address)
        middle = size // 2
        address_part1 = int(self.contract_address[:middle], 16)
        address_part2 = int(self.contract_address[middle:], 16)
        return address_part1, address_part2

    def to_zkvm_input(self) -> list[int]:
        address_part1, address_part2 = self.split_address()
        return [
            address_part1,
            address_part2,
            self.days_ago_added,
            int(self.is_active),
            self.volume,
            self.market_cap,
            self.total_supply,
            int(self.has_source_code),
        ]

    def compute(self) -> Computation:
        params = self.to_zkvm_input()
        return Docker.run_compute_witness(params)


class CoinMarketCap:
    @staticmethod
    def get_token_metadata(contract_address: str, coinmarketcap_api_key: str) -> dict:
        headers = {
            "Accepts": "application/json",
            "X-CMC_PRO_API_KEY": coinmarketcap_api_key,
        }
        parameters = {"address": contract_address}
        logger.info(f"Getting token metadata for {contract_address}")
        response = requests.get(COINMARKETCAP_API_URL + "v2/cryptocurrency/info", headers=headers, params=parameters)
        logger.info(f"Response: {response.json()}")
        return response.json()

    @staticmethod
    def get_token_market_data(token_id: str, coinmarketcap_api_key: str) -> dict:
        headers = {
            "Accepts": "application/json",
            "X-CMC_PRO_API_KEY": coinmarketcap_api_key,
        }
        parameters = {
            "id": token_id,
            "time_start": "2024-01-01",
            "time_end": "2025-02-15",
            "interval": "365d",
        }
        logger.info(f"Getting token market data for {token_id}")
        response = requests.get(COINMARKETCAP_API_URL + "v2/cryptocurrency/quotes/historical", headers=headers, params=parameters)
        logger.info(f"Response: {response.json()}")
        # NOTE: This requires a paid plan, so we'll just return mock data for now
        return {
            "data": {
                "id": token_id,
                "name": "Lombard Bitcoin",
                "symbol": "LBTC",
                "is_active": 1,
                "is_fiat": 0,
                "quotes": [
                    {
                        "timestamp": "2018-06-22T19:29:37.000Z",
                        "quote": {
                            "USD": {
                                "price": random.randint(100, 1000000),
                                "volume_24h": random.randint(100, 1000000),
                                "market_cap": random.randint(100, 1000000),
                                "circulating_supply": random.randint(100, 1000000),
                                "total_supply": random.randint(100, 1000000),
                                "timestamp": "2018-06-22T19:29:37.000Z",
                            }
                        },
                    }
                ],
            },
            "status": {"timestamp": "2025-02-15T04:00:32.787Z", "error_code": 0, "error_message": "", "elapsed": 10, "credit_count": 1, "notice": ""},
        }


class Etherscan:
    @staticmethod
    def get_contract_details(contract_address: str, etherscan_api_key: str) -> dict:
        logger.info(f"Getting contract details for {contract_address}")
        params = {"module": "contract", "action": "getsourcecode", "address": contract_address, "apikey": etherscan_api_key}
        response = requests.get(ETHERSCAN_API_URL, params=params)
        logger.info(f"Response: {response.json()}")
        return response.json()

    @staticmethod
    def get_erc20_total_supply(contract_address: str, etherscan_api_key: str) -> dict:
        logger.info(f"Getting ERC20 total supply for {contract_address}")
        params = {"module": "stats", "action": "tokensupply", "contractaddress": contract_address, "apikey": etherscan_api_key}
        response = requests.get(ETHERSCAN_API_URL, params=params)
        logger.info(f"Response: {response.json()}")
        return response.json()


class Docker:
    @staticmethod
    def get_zokrates_container_name():
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError("❌ No running ZoKrates container found. Start ZoKrates first!")
        containers = result.stdout.strip().split("\n")
        for line in containers:
            logger.info(f"Container line: {line}")
            if "zokrates" in line.lower():
                return line.split()[-1]
        raise RuntimeError("❌ No running ZoKrates container found. Start ZoKrates first!")

    @staticmethod
    def run_compute_witness(params: list[int]) -> Computation:
        container_name = Docker.get_zokrates_container_name()
        cmd = [
            "docker",
            "exec",
            "-it",
            container_name,
            "bash",
            "-c",
            f"cd /home/zokrates/krates && zokrates compute-witness -a {' '.join(map(str, params))} && zokrates generate-proof",
        ]
        logger.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"❌ Error in compute-witness:\n{result.stderr}")
            raise RuntimeError("ZoKrates compute-witness failed!")
        logger.info(f"✅ ZoKrates compute-witness output:\n{result.stdout}")
        return Docker.get_results()

    @staticmethod
    def get_results() -> Computation:
        container_name = Docker.get_zokrates_container_name()
        cmd = ["docker", "exec", "-it", container_name, "bash", "-c", "cd /home/zokrates/krates && cat proof.json"]
        logger.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"❌ Error in get-calculation:\n{result.stderr}")
            raise RuntimeError("ZoKrates get-calculation failed!")
        logger.info(f"✅ ZoKrates get-calculation output:\n{result.stdout}")
        results = json.loads(result.stdout)
        return Computation(
            curve=results["curve"],
            proof=Proof(
                a=results["proof"]["a"],
                b=results["proof"]["b"],
                c=results["proof"]["c"],
            ),
            scheme=results["scheme"],
            inputs=Inputs(
                score=int(results["inputs"][0], 16),
                signature=int(results["inputs"][1], 16),
                address_part1=int(results["inputs"][2], 16),
                address_part2=int(results["inputs"][3], 16),
            ),
        )


class Contract:
    @staticmethod
    def get_abi() -> dict:
        with open("krates/verifier.abi", "r") as f:
            return json.load(f)

    @staticmethod
    def verify(inputs: Inputs, proof: Proof, private_key: str, verifier_contract_address: str, ethereum_rpc_url: str) -> bool:
        w3 = Web3(Web3.HTTPProvider(ethereum_rpc_url))
        contract = w3.eth.contract(address=verifier_contract_address, abi=Contract.get_abi())
        logger.info(f"Verifying proof with inputs: {inputs} and proof: {proof}")
        tx = contract.functions.verifyTx(proof.to_solidity(), inputs.to_solidity()).build_transaction(
            {
                "from": w3.eth.accounts[0],
                "gas": 500000,
                "gasPrice": w3.to_wei("10", "gwei"),
                "nonce": w3.eth.get_transaction_count(w3.eth.accounts[0]),
            }
        )
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info(f"Receipt: {receipt}")
        logger.info(f"✅ Transaction successful: {tx_hash.hex()}")
        return contract.functions.verifyTx(proof.to_solidity(), inputs.to_solidity()).call()


@begin.start
def main(
    private_key="",
    etherscan_api_key="",
    coinmarketcap_api_key="",
    target_contract_address="",
    verifier_contract_address="",
    ethereum_rpc_url="",
):
    assert private_key, "Private key is required"
    assert etherscan_api_key, "Etherscan API key is required"
    assert coinmarketcap_api_key, "CoinMarketCap API key is required"
    assert target_contract_address, "Target contract address is required"
    assert verifier_contract_address, "Verifier contract address is required"
    assert ethereum_rpc_url, "Ethereum RPC URL is required"

    # First, get the token metadata
    print("Coinbase metadata:")
    coinbase_details = CoinMarketCap.get_token_metadata(target_contract_address, coinmarketcap_api_key)
    print(json.dumps(coinbase_details, indent=4))

    # Then, get the CoinMarketCap ID
    coinmarketcap_id = list(coinbase_details["data"].keys())[0]
    print("CoinMarketCap ID:", coinmarketcap_id)

    # Then, get the CoinMarketCap market data
    print("CoinMarketCap market data:")
    coinmarketcap_market_data = CoinMarketCap.get_token_market_data(coinmarketcap_id, coinmarketcap_api_key)
    print(json.dumps(coinmarketcap_market_data, indent=4))

    # Then, get the contract details
    print("Contract details:")
    contract_details = Etherscan.get_contract_details(target_contract_address, etherscan_api_key)
    print(json.dumps(contract_details, indent=4))

    # Then, get the ERC20 token total supply
    print("Get ERC20 token total supply:")
    total_supply_details = Etherscan.get_erc20_total_supply(target_contract_address, etherscan_api_key)
    print(json.dumps(total_supply_details, indent=4))

    # Then, get the date added
    date_added = coinbase_details["data"][coinmarketcap_id]["date_added"]
    days_ago_added = (datetime.now() - datetime.strptime(date_added, "%Y-%m-%dT%H:%M:%S.%fZ")).days

    # Then, get the stats
    stats = Stats(
        contract_address=target_contract_address,
        has_source_code=contract_details["result"][0]["SourceCode"] is not None if contract_details["result"] else False,
        is_active=coinmarketcap_market_data["data"]["is_active"],
        volume=coinmarketcap_market_data["data"]["quotes"][0]["quote"]["USD"]["volume_24h"],
        market_cap=coinmarketcap_market_data["data"]["quotes"][0]["quote"]["USD"]["market_cap"],
        total_supply=int(total_supply_details["result"]),
        name=coinbase_details["data"][coinmarketcap_id]["name"],
        symbol=coinbase_details["data"][coinmarketcap_id]["symbol"],
        days_ago_added=days_ago_added,
    )
    print(json.dumps(stats.to_dict(), indent=4))

    # Then, compute the score
    print("Calculating score...")
    computation = stats.compute()
    print(f"Calculation: {computation}")

    # Now, verify the score and its signature together with the zk proof
    other_inputs = Inputs(
        score=computation.inputs.score,
        signature=computation.inputs.signature,
        address_part1=stats.split_address()[0],
        address_part2=stats.split_address()[1],
    )
    receipt = Contract.verify(other_inputs, computation.proof, private_key, verifier_contract_address, ethereum_rpc_url)

    # Print the final results
    print(f"Certified: {receipt}")
    print(f"Score: {other_inputs.get_normalized_score()}")
    print(f"Contract address: {target_contract_address}")
    if not receipt:
        raise RuntimeError("❌ Proof verification failed!")

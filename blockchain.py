import hashlib
import time


DIFFICULTY = 0x1E200000


def double_sha256(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()


def calculate_target(bits):
    exponent = bits >> 24
    coefficient = bits & 0xFFFFFF
    return coefficient * (2 ** (8 * (exponent - 3)))


class Output:
    def __init__(self, value, index, script):
        self.value = value
        self.index = index
        self.script = script

    def to_string(self):
        return str(self.value) + str(self.index) + self.script


def calculate_merkle_root(transactions):
    if not transactions:
        return ""
    hashes = [tx.tx_hash for tx in transactions]
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])
        new_hashes = []
        for i in range(0, len(hashes), 2):
            concat_data = hashes[i] + hashes[i + 1]
            new_hashes.append(double_sha256(concat_data))
        hashes = new_hashes
    return hashes[0]


class Transaction:
    def __init__(self, inputs, outputs, tx_hash=None):
        self.inputs = inputs
        self.outputs = outputs
        self.tx_hash = tx_hash or self.calc_hash()

    def calc_hash(self):
        out_data = ""
        for output in self.outputs:
            out_data += output.to_string()

        data = (
            "".join(self.inputs)
            + out_data
            + str(len(self.inputs))
            + str(len(self.outputs))
        )
        return double_sha256(data)


class Block:
    def __init__(self, height, prev_hash, transactions, nonce=0, timestamp=None):
        self.height = height
        self.prev_hash = prev_hash
        self.transactions = transactions
        self.merkle_root = calculate_merkle_root(transactions)
        self.timestamp = int(time.time()) if timestamp is None else timestamp
        self.bits = DIFFICULTY
        self.nonce = nonce
        self.block_hash = None


def tx_to_dict(tx):
    return {
        "inputs": tx.inputs,
        "outputs": [
            {
                "value": output.value,
                "index": output.index,
                "script": output.script,
            }
            for output in tx.outputs
        ],
        "tx_hash": tx.tx_hash,
    }


def tx_from_dict(data):
    outputs = []
    for output in data["outputs"]:
        outputs.append(Output(output["value"], output["index"], output["script"]))
    return Transaction(data["inputs"], outputs, tx_hash=data["tx_hash"])


def block_to_dict(block):
    return {
        "height": block.height,
        "prev_hash": block.prev_hash,
        "transactions": [tx_to_dict(tx) for tx in block.transactions],
        "timestamp": block.timestamp,
        "nonce": block.nonce,
        "block_hash": block.block_hash,
    }


def block_from_dict(data):
    transactions = [tx_from_dict(tx) for tx in data["transactions"]]
    block = Block(
        data["height"],
        data["prev_hash"],
        transactions,
        nonce=data["nonce"],
        timestamp=data["timestamp"],
    )
    block.block_hash = data["block_hash"]
    return block


def block_text(block):
    return (
        str(block.timestamp)
        + block.merkle_root
        + str(block.bits)
        + str(block.nonce)
        + block.prev_hash
    )


def validate_block(block, prev):
    if block.height != prev.height + 1:
        return False
    if block.prev_hash != prev.block_hash:
        return False
    block_hash = double_sha256(block_text(block))
    if block.block_hash != block_hash:
        return False
    return int(block_hash, 16) <= calculate_target(DIFFICULTY)


class Blockchain:
    def __init__(self):
        self.chain = []
        self.create_genesis_block()

    def create_genesis_block(self):
        genesis_out = Output(50000, 0, "Genesis Output")
        genesis_tx = Transaction(["0" * 64], [genesis_out])
        genesis = Block(0, "0" * 64, [genesis_tx], timestamp=0)
        genesis.block_hash = double_sha256(block_text(genesis))
        self.chain.append(genesis)

    def get_last_block(self):
        return self.chain[-1]

    def add_block(self, block):
        self.chain.append(block)

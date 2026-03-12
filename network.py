import json
import os
import random
import socket
import struct
import threading
import time
import uuid

from blockchain import *


MAX_PEERS = 2


def send_msg(sock, data):
    raw = json.dumps(data).encode()
    sock.sendall(struct.pack("!I", len(raw)) + raw)


def recv_msg(sock):
    hdr = sock.recv(4)
    if len(hdr) < 4:
        return None
    n = struct.unpack("!I", hdr)[0]
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return json.loads(buf)


def send_and_recv(host, port, msg, timeout=3):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        send_msg(s, msg)
        return recv_msg(s)
    except Exception:
        return None
    finally:
        s.close()


def start_server(host, port, handler):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)

    def handle(conn, addr):
        try:
            msg = recv_msg(conn)
            if msg:
                resp = handler(msg, addr[0])
                if resp:
                    send_msg(conn, resp)
        except Exception:
            pass
        finally:
            conn.close()

    def loop():
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle, args=(conn, addr), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv


def get_my_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.error:
        return "127.0.0.1"


class Node:
    def __init__(self):
        self.name = os.environ.get("NODE_NAME", "node")
        self.port = int(os.environ.get("LISTEN_PORT", "58333"))
        self.reg_host = os.environ.get("REGISTRAR_HOST", "registrar")
        self.reg_port = int(os.environ.get("REGISTRAR_PORT", "58333"))

        self.ip = get_my_ip()
        self.blockchain = Blockchain()

        self.peers = set()
        self.connected_peers = set()
        self.mempool = {}
        self.seen_tx = set()
        self.seen_blocks = {self.blockchain.get_last_block().block_hash}
        self.lock = threading.Lock()
        self.can_mine = False

    def log(self, msg):
        print(f"[{self.name}] {msg}", flush=True)

    def on_message(self, msg, sender):
        t = msg.get("type")

        if t == "handshake":
            self._add_peer(msg.get("addr", sender))
            with self.lock:
                return {
                    "type": "handshake_ack",
                    "peers": list(self.peers),
                }

        elif t == "new_tx":
            tx = tx_from_dict(msg["transaction"])
            if self._add_tx(tx):
                self.log(f"got tx {tx.tx_hash[:12]}")
                threading.Thread(
                    target=self._broadcast,
                    args=({"type": "new_tx", "transaction": tx_to_dict(tx)},),
                    daemon=True,
                ).start()
            return {"type": "ack"}

        elif t == "new_block":
            block = block_from_dict(msg["block"])
            if self._accept_block(block):
                self.log(f"got block {block.height}")
                threading.Thread(
                    target=self._broadcast,
                    args=({"type": "new_block", "block": block_to_dict(block)},),
                    daemon=True,
                ).start()
            return {"type": "ack"}

        return None

    def _add_peer(self, ip):
        if ip == self.ip:
            return
        with self.lock:
            if len(self.peers) < MAX_PEERS:
                self.peers.add(ip)

    def _add_tx(self, tx):
        with self.lock:
            if tx.tx_hash in self.seen_tx:
                return False
            self.seen_tx.add(tx.tx_hash)
            self.mempool[tx.tx_hash] = tx
        return True

    def _accept_block(self, block):
        block_hash = block.block_hash
        with self.lock:
            if block_hash in self.seen_blocks:
                return False
            self.seen_blocks.add(block_hash)
            if not validate_block(block, self.blockchain.get_last_block()):
                return False
            self.blockchain.add_block(block)
            for tx in block.transactions:
                self.mempool.pop(tx.tx_hash, None)
        return True

    def _broadcast(self, payload):
        with self.lock:
            targets = list(self.peers)
        for p in targets:
            send_and_recv(p, self.port, payload, timeout=2)

    def _register(self):
        while True:
            resp = send_and_recv(
                self.reg_host,
                self.reg_port,
                {
                    "type": "register",
                    "addr": self.ip,
                },
            )
            if resp:
                boot = resp.get("bootstrap")
                self.log("registered")
                if boot:
                    self._add_peer(boot)
                return
            time.sleep(1)

    def _do_handshakes(self):
        while True:
            with self.lock:
                todo = [p for p in self.peers if p not in self.connected_peers]

            for p in todo:
                resp = send_and_recv(
                    p,
                    self.port,
                    {
                        "type": "handshake",
                        "addr": self.ip,
                    },
                )
                if resp and resp.get("type") == "handshake_ack":
                    with self.lock:
                        self.connected_peers.add(p)
                    for peer in resp.get("peers", []):
                        self._add_peer(peer)
                    self.log(f"connected to {p}")

            with self.lock:
                if self.peers and not self.can_mine:
                    self.can_mine = True
                    self.log("ready to mine")
            time.sleep(1)

    def _gen_transactions(self):
        while not self.can_mine:
            time.sleep(0.5)
        while True:
            time.sleep(random.randint(2, 5))
            inp = double_sha256(self.name + uuid.uuid4().hex)
            out = Output(
                random.randint(1, 25),
                0,
                f"Pay user{random.randint(1, 9)} from {self.name}",
            )
            tx = Transaction([inp], [out])
            if self._add_tx(tx):
                self.log(f"made tx {tx.tx_hash[:12]}")
                self._broadcast({"type": "new_tx", "transaction": tx_to_dict(tx)})

    def _mine_loop(self):
        while not self.can_mine:
            time.sleep(0.5)
        target = calculate_target(DIFFICULTY)
        while True:
            with self.lock:
                pending = list(self.mempool.values())
            if not pending:
                time.sleep(0.5)
                continue

            prev = self.blockchain.get_last_block()
            block = Block(prev.height + 1, prev.block_hash, pending)

            nonce = 0
            while True:
                block.nonce = nonce
                block_hash = double_sha256(block_text(block))
                if int(block_hash, 16) <= target:
                    block.block_hash = block_hash
                    break
                nonce += 1

            if self._accept_block(block):
                self.log(f"mined block {block.height} ({len(block.transactions)} tx)")
                self._broadcast({"type": "new_block", "block": block_to_dict(block)})
                time.sleep(random.randint(0, 3))

    def run(self):
        start_server("0.0.0.0", self.port, self.on_message)
        self.log(f"listening on {self.port}")

        threading.Thread(target=self._register, daemon=True).start()
        threading.Thread(target=self._do_handshakes, daemon=True).start()
        time.sleep(2)
        threading.Thread(target=self._gen_transactions, daemon=True).start()
        threading.Thread(target=self._mine_loop, daemon=True).start()

        try:
            while True:
                time.sleep(30)
        except KeyboardInterrupt:
            pass


_known_nodes = []
_reg_lock = threading.Lock()


def _handle_register(msg, addr):
    if msg.get("type") != "register":
        return None
    ip = msg.get("addr", addr)
    with _reg_lock:
        bootstrap = None
        if _known_nodes and _known_nodes[-1] != ip:
            bootstrap = _known_nodes[-1]
        if ip in _known_nodes:
            _known_nodes.remove(ip)
        _known_nodes.append(ip)
    print(f"[registrar] registered {ip}", flush=True)
    return {"type": "register_ack", "bootstrap": bootstrap}


def run_registrar(port):
    start_server("0.0.0.0", port, _handle_register)
    print(f"[registrar] listening on {port}", flush=True)
    while True:
        time.sleep(60)

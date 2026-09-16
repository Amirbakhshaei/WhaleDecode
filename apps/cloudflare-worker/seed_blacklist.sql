-- Blacklist seed: CEX clearing + bridge vaults + MEV bots
-- ponytail: minimal seed; refresh from external feed periodically

INSERT OR IGNORE INTO blacklisted_addresses (address, reason) VALUES
('0x21a31ee1afc51d94c2efccaa2092ad1028285549', 'CEX: Binance 15 hot wallet'),
('0xdfd5293d8e347dfe59e90efd55b2956a1343963d', 'CEX: Binance 16 hot wallet'),
('0x56eddb7aa87536c09ccc2793473599fd21a8b17f', 'CEX: Binance 17 hot wallet'),
('0xf977814e90da44bfa03b6295a0616a897441acec', 'CEX: Binance Hot Wallet 20'),
('0x61189da79177950a7272c88c6058b96d4bcd6be2', 'CEX: Binance US'),
('0x5a52e96bacdabb82fd05763e25335261b270efcb', 'CEX: Binance 28'),
('0x503828976d22510aad0201ac7ec88293211d23da', 'CEX: Coinbase 2'),
('0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740', 'CEX: Coinbase 3'),
('0xbdf02a737d241c95eb32cb53cb568609d0a115f9', 'CEX: Coinbase Cold Wallet 17'),
('0x2c8fbb630289363ac80705a1a61273f76fd5a161', 'CEX: OKX 4'),
('0x59fae149a8f8ec74d5bc038f8b76d25b136b9573', 'CEX: OKX 5'),
('0xd6216fc19db775df9774a6e33526131da7d19a2c', 'CEX: KuCoin 6'),
('0x738cf6903e6c4e699d1c2dd9ab8b67fcdb3121ea', 'CEX: KuCoin 12'),
('0xc20c13d2303eeaeeaeb7f73babf7014bce6d130a', 'CEX: Bybit locked / hot wallet seed'),
('0x5288c571fd7ad117bea99bf60fe0846c4e84f933', 'Bridge: Arbitrum L2 Gateway Router'),
('0xc931f61b1534eb21d8c11b24f3f5ab2471d4ab50', 'Bridge: Multichain Router V4'),
('0x650af55d5877f289837c30b94af91538a7504b76', 'Bridge: Multichain Router V6'),
('0x72ce9c846789fdb6fc1f34ac4ad25dd9ef7031ef', 'Bridge: Arbitrum L1 Gateway Router'),
('0xe95fd76cf16008c12ff3b3a937cb16cd9cc20284', 'Bridge: Multichain Router V3'),
('0x6b7a87899490ece95443e979ca9485cbe7e71522', 'Bridge: Multichain Router V4'),
('0xdeadc0de0000000000000000000000000000000000', 'MEV bot / automated router — seed placeholder; verify via feed'),
('0xdeadbeef0000000000000000000000000000000000', 'MEV bot — seed placeholder; verify via feed');

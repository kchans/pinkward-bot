alter table wallets alter column cash set default 100000;
update wallets set cash = 100000 where cash = 10000;

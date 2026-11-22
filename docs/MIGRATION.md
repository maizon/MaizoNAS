# Migração do servidor anterior

Quando encontra o estado existente do gerenciador em `~/.local/share/ps2-downloads`, o instalador reutiliza login, segredos internos de RPC, histórico, sessões, catálogo e caminhos de mídia. Não copia jogos ou filmes e não apaga arquivos da coleção.

O código instalado fica em `/opt/maizonas`, as configurações principais em `/etc/maizonas`, e o launcher em `/usr/local/sbin/maizonasctl`. O runtime existente do SliTaz pode ser reutilizado. As chamadas antigas de inicialização do downloader e do conversor são substituídas pela chamada única ao MaizoNAS.

A interface inicial passa a ser a coleção. Downloads ficam em `/downloads`; o conversor em `/convert`; administração em `/settings`. A porta antiga do conversor recebe um redirecionamento. Os serviços antigos são parados apenas na etapa final de uma instalação com início habilitado.

Antes de migrar, espere downloads, extrações e conversões terminarem. A sessão de downloads é mantida; links que já expiraram continuam exigindo um novo link. A instalação não transforma links expirados em válidos.

Os backups de configurações Samba e das versões anteriores da aplicação ficam em `/var/lib/maizonas/backups`. Configurações de rede pendentes são guardadas em `/var/lib/maizonas/network-transactions`, com acesso exclusivo de root.

Para uma reversão manual, pare o MaizoNAS, restaure a configuração anterior e reative os serviços anteriores usando os backups.

# Arquitetura

`maizonas/app.py` é o único servidor HTTP, com coleção como rota inicial e autenticação PBKDF2 compartilhada. Ele reutiliza o importador/downloader e o catálogo SQLite em `legacy/`, e integra o conversor em `converter/` sem proxies públicos ou iframes. O RPC do aria2 permanece em loopback e não é exposto diretamente ao navegador.

`maizonas/admin.py` é um broker local com privilégios administrativos. Aceita apenas métodos definidos, por socket Unix, e valida SO_PEERCRED. Ele não recebe comandos shell nem nomes livres de pacotes. Rede, Samba e caminhos passam por validadores. A interface HTTP é executada com o UID/GID do usuário escolhido e não como root.

O broker observa alterações dos endereços IPv4 das interfaces e reconfigura a escuta SMB com intervalo de proteção para evitar reinícios contínuos. Não reinicia o Samba por alterações de endereços IPv6 temporários. O diagnóstico SMB tenta autenticação de convidado e listagem de arquivos; não se limita a examinar o processo ou uma porta TCP.

## Rede

Os adaptadores são selecionados pela presença de NetworkManager, SliTaz ou systemd-networkd. Eles escrevem arquivos próprios ou configurações específicas da rede, sempre após validação. A rede Wi-Fi com SSID/senha informados usa WPA-PSK; redes empresariais exigem configuração externa do respectivo gerenciador.

Cada alteração mantém uma transação privada com cópias dos arquivos envolvidos e dados de restauração. A confirmação salva a intenção no JSON principal. Falha, expiração ou reinício do broker sem confirmação tenta restaurar a rede anterior. A reversão depende de o sistema operacional e o gerenciador continuarem funcionando; não substitui acesso físico de recuperação.

## Runtime no SliTaz

O aplicativo utiliza Python e ferramentas modernas no runtime. `/home`, `/srv` e dispositivos/arquivos de execução são compartilhados. O broker acessa os arquivos e comandos do anfitrião pela raiz real do processo init em `/proc/1/root` (o runtime usa os mesmos namespaces do host), usando argumentos separados em subprocessos; o Samba servido ao PS2 pertence ao anfitrião.

A atualização conserva o inode do diretório instalado para que os bind mounts do runtime continuem mostrando os arquivos novos. O launcher cria processos separados para web e administração; a web perde privilégios antes de importar o servidor.

## Persistência

Os arquivos de mídia ficam fora da instalação. Configurações e backups administrativos não entram no pacote nem no repositório. Atualizações guardam a versão anterior do código. Os originais de conversão não são removidos automaticamente.

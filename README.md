# MaizoNAS

Servidor Linux com **coleção na página inicial**, downloads, conversão de DVDs/vídeos e um painel de administração no mesmo endereço.

Esta é a versão Linux do servidor. O antigo aplicativo Android foi substituído; seu histórico permanece no Git.

## Instalar

Baixe o [pacote instalável](https://github.com/maizon/MaizoNAS/raw/refs/heads/main/downloads/maizonas-2.0.0.tar.gz), extraia e execute `sudo sh install.sh --user "$USER"`. Confira o SHA-256 publicado ao lado do arquivo.

Ou baixe o repositório e execute:

```sh
git clone https://github.com/maizon/MaizoNAS.git
cd MaizoNAS
sudo sh install.sh --user "$USER"
```

Sem Git, baixe o ZIP do repositório, extraia e execute o mesmo `install.sh`. Também é possível usar o pacote `.tar.gz` gerado por `scripts/package.py`.

O instalador instala as dependências, prepara o serviço, gera a senha inicial e mostra o endereço da interface. Em uma instalação nova o usuário web é `admin`; guarde a senha exibida no terminal. Na migração do servidor existente, conserva o login e a senha já usados no downloader.

Abra `http://IP_DO_COMPUTADOR:8088/`. A interface funciona também em celular na mesma rede. O instalador não abre portas do roteador nem publica o servidor na internet.

### SliTaz

O SliTaz antigo pode não ter Python moderno ou bibliotecas compatíveis. O instalador reutiliza `/opt/opl-runtime` quando disponível; em uma instalação nova pode baixar um minirootfs oficial Alpine, verificar o SHA-256 e criar `/opt/maizonas-runtime`.

O runtime compartilha a rede e as pastas de dados, mas **não substitui a libc do SliTaz**. O Samba e a configuração da rede continuam no sistema anfitrião. O código web roda como usuário comum; um broker local, separado, executa as operações administrativas permitidas.

### Outras distribuições

O instalador possui receitas para APT, DNF, Pacman, Zypper, APK e Tazpkg; inicialização com systemd, OpenRC e SysV/SliTaz. São necessários Linux, Python 3.9 ou posterior e pacotes disponíveis nos repositórios da distribuição. Sistemas sem uma dessas combinações recebem uma mensagem de diagnóstico em vez de serem declarados compatíveis silenciosamente.

O controle de rede possui adaptadores para SliTaz, NetworkManager e systemd-networkd. Em outro gerenciador a inspeção permanece disponível, mas as mudanças de rede são bloqueadas. Repositórios com restrições de codecs podem exigir configuração adicional da distribuição para o modo de conversão; o instalador não adiciona repositórios de terceiros sem escolha do administrador.

**Validação realizada:** SliTaz com o runtime existente, testes reais de mídias/DVD e interface no Firefox. As receitas de seis gerenciadores de pacotes são testadas com comandos simulados; isso não equivale a testar todas as distribuições, versões e arquiteturas em máquinas reais.

## Uma interface, quatro áreas

- **Coleção `/`:** jogos e filmes, capas, busca, filtros, nomes editáveis e links de download com retomada. Arquivos existentes permanecem nos lugares originais.
- **Downloads `/downloads`:** links diretos e torrents, fila, pausa, retomada, atualização de links expirados, limites de velocidade e extração de arquivos compactados. A opção Filmes envia ISOs de filmes e formatos comuns de vídeo para a pasta de filmes. Não inclui catálogo de ROMs, jogos ou fontes de conteúdo.
- **Conversor `/convert`:** títulos de DVDs, AVI/MP4 sem perdas ou compatíveis e MKV com fluxos originais. Fila, progresso, cancelamento e validação de dados/tempos. Originais preservados.
- **Servidor `/settings`:** estado das interfaces e do disco, portas, pastas, compartilhamento SMB, compatibilidade OPL, modo de rede, DHCP/IP fixo, rede Wi-Fi, teste SMB real, dependências e registros.

A interface usa um único login. O login administrativo web é separado do acesso SMB convidado.

## Rede automática e avançada

Modos: Automático, Ethernet, Wi-Fi ou Ambas. Automático prefere cabo com sinal e pode alternar para a rede Wi-Fi já configurada. Ambas mantém Ethernet como rota preferencial; não é agregação de banda nem soma das velocidades.

Antes de alterar a rede, a interface mostra uma prévia. Depois de aplicar, há **180 segundos para confirmar o acesso**. Sem confirmação, a configuração anterior é restaurada. Backups da transação ficam em pasta privada do sistema; uma reinicialização do broker recupera transações não confirmadas. Sempre mantenha acesso local ao computador ao modificar uma rede remota.

Um IP recebido por DHCP pode mudar. Para usar sempre o mesmo endereço no OPL, faça uma reserva DHCP no roteador. O MaizoNAS não administra roteadores externos.

## PS2 / OPL

O painel mostra o endereço IPv4, a porta e o compartilhamento atuais. Padrões:

```text
Servidor: IP do computador mostrado no painel
Porta: 445
Compartilhamento: PS2
Usuário SMB: vazio
Senha SMB: vazia
```

A opção OPL ativa SMB1/NT1 e os parâmetros de compatibilidade necessários. SMB1 e acesso convidado devem ser usados em uma rede local confiável. O Samba é configurado com escuta explícita em IPv4; o broker acompanha mudanças de endereço para evitar o problema de serviço apenas IPv6 ou preso a um endereço antigo.

Configurações anteriores do Samba são guardadas em `/var/lib/maizonas/backups`. A configuração gerenciada é incluída em `/etc/samba/maizonas.conf`, preservando as outras seções do arquivo principal. O compartilhamento com o nome escolhido e as opções globais de compatibilidade passam a ser administrados pelo programa.

## Conversão e qualidade

**Sem perdas não significa compatibilidade universal.**

- AVI sem perdas: FFV1, com áudio original ou PCM. Requer player com FFV1; não é um AVI Xvid destinado ao SMS do PS2.
- MP4 sem perdas: H.264 CRF 0, com áudio original compatível ou ALAC para PCM inteiro. Alguns aparelhos e navegadores não aceitam esse perfil.
- MKV original: copia os fluxos comprimidos originais sem recodificação.
- AVI compatível: Xvid de alta qualidade e MP3. Tem perdas de recompressão.
- MP4 compatível: H.264 CRF 16 e AAC. Tem perdas de recompressão.

Redimensionar altera os pixels; por isso os perfis sem perdas mantêm resolução original. Cada título de DVD gera um arquivo separado, sem concatenar menus, extras e episódios cegamente. Menus interativos e legendas não são convertidos.

O motor `dvdvideo` usa a navegação do DVD para obter os tempos dos títulos. Antes de publicar uma saída sem perdas, compara hashes dos dados decodificados ou dos fluxos originais, conforme o perfil. Também compara a linha de tempo do vídeo e os inícios/fins do áudio; discrepâncias acima de 40 ms são recusadas. No AVI, restaura o início das faixas no cabeçalho padrão do formato, respeitando sua precisão temporal. Isso preserva a sincronização da origem; não corrige um atraso que já exista nela e não é uma avaliação perceptiva de sincronismo labial.

Se o FFmpeg da distribuição não possui navegação DVD, o instalador pode compilar um motor dedicado. Esse processo é automático, mas pode levar vários minutos. Não há remoção de proteção de cópia.

## Administração

```sh
sudo maizonasctl status
sudo maizonasctl start
sudo maizonasctl stop
sudo maizonasctl restart
sudo maizonasctl restart-web
```

Configuração: `/etc/maizonas/config.json`, com senha web derivada por PBKDF2. Nunca envie esse arquivo ao GitHub. O estado dos downloads pode conter URLs privadas e senhas de arquivos; também não deve ser publicado.

O broker usa socket Unix com permissões e validação da identidade do processo. Não existe endpoint para comandos shell arbitrários. Mudanças de pastas são limitadas a diretórios de dados e recusam links simbólicos. Operações web exigem login e verificam a origem dos POSTs.

Opções úteis:

```sh
sudo sh install.sh --user "$USER" --no-start
sudo sh install.sh --user "$USER" --no-dvd-build
sudo sh install.sh --user "$USER" --runtime /caminho/do/runtime
```

`--skip-packages` é para ambientes que já têm as dependências, não a opção recomendada para uma instalação nova. Para atualizar, baixe a nova versão e execute o instalador novamente. Ele mantém as pastas e o estado. Não atualize enquanto houver conversões em andamento.

## Remover a aplicação

Execute `sudo sh /opt/maizonas/uninstall.sh`. Remove a interface e sua inicialização, mas mantém mídias, estado, configuração, backups, Samba e pacotes do sistema. Não há exclusão automática de jogos ou filmes.

## Testes e pacote

```sh
python3 tests/test_core.py
python3 tests/test_legacy.py
FILMES_ENGINE=/caminho/do/engine/bin python3 tests/test_converter.py
python3 scripts/package.py
```

Os testes de conversão exigem `dvdauthor`, `genisoimage` e um FFmpeg compilado com `dvdvideo`, além das dependências principais. Usam arquivos próprios em pastas temporárias; não convertem nem apagam a coleção pessoal.

No SliTaz com runtime:

```sh
sudo chroot /opt/opl-runtime python3 /home/SEU_USUARIO/MaizoNAS/tests/test_core.py
```

Veja [arquitetura](docs/ARCHITECTURE.md), [compatibilidade](docs/COMPATIBILITY.md) e [migração](docs/MIGRATION.md).

Licença: GPL-3.0, conforme [LICENSE](LICENSE). FFmpeg, Samba e demais dependências mantêm suas próprias licenças e são instalados separadamente.

# MaizonNAS Android

Aplicativo Android independente para servir a biblioteca do PS2 por **SMBv1 e UDPBD**.
Não depende de Termux, Ubuntu ou PRoot. Root é opcional para acesso a pastas restritas.

[![Android APK](https://github.com/maizon/MaizoNAS/actions/workflows/android.yml/badge.svg)](https://github.com/maizon/MaizoNAS/actions/workflows/android.yml)

## Baixar o APK sem compilar no celular

1. Abra [Actions → Android APK](https://github.com/maizon/MaizoNAS/actions/workflows/android.yml).
2. Escolha uma execução concluída com sucesso.
3. Em **Artifacts**, baixe **MaizonNAS-Android-debug** e extraia o ZIP.
4. Instale `MaizonNAS-Android-debug.apk` e permita a instalação pelo aplicativo usado para abrir o APK.

O GitHub exige login para baixar artefatos. Eles ficam disponíveis por 30 dias;
**Run workflow** gera outro APK. Toda a compilação ocorre nos runners do GitHub.
O APK inicial é de teste, assinado com chave de debug; builds diferentes podem exigir
reinstalação, apagando as preferências. Uma distribuição estável deve usar chave de release própria.

## Recursos

- Seleção rápida **SMBv1**, **UDPBD** ou **ambos**; UDPFS disponível como opção adicional.
- Iniciar/parar a sessão e reiniciar a seleção com confirmação.
- Status atualizado a cada segundo, taxa de transferência, último cliente e logs copiáveis.
- Biblioteca com busca por nome em `DVD`, `CD`, `POPS` e `APPS`.
- Nome do painel, tema do sistema/claro/escuro, quatro cores e interface compacta.
- Serviço em primeiro plano e wake lock para manter a transferência com a tela apagada.
- Pasta interna, cartão/pendrive pelo seletor Android ou dispositivo USB inteiro.
- Acesso normal, root ou Shizuku; os dois últimos são opcionais.
- Compartilhamento **somente leitura**, incluindo o acesso a blocos UDPBD/UDPFS.

A seleção é aplicada antes de iniciar: para mudar os protocolos, pare a sessão primeiro.
O botão de reiniciar atua em todos os servidores da seleção atual.

## Uso no celular e no PS2

1. Instale o APK e autorize notificações e acesso aos arquivos quando necessário.
2. Selecione `/storage/emulated/0/PS2` ou a pasta de jogos desejada.
3. Escolha o protocolo e toque em **Iniciar**.
4. Use o IP mostrado no aplicativo nas configurações do PS2.

| Protocolo | Porta | Configuração |
|---|---|---|
| SMBv1 | TCP **1445** | Share **PS2**, usuário guest, senha vazia |
| UDPBD v2 | UDP **48573** | Loader compatível com UDPBD v2/exFAT; descoberta na rede local |
| UDPFS opcional | UDP **62966** | Loader compatível, como Neutrino |

Use a mesma rede local; Ethernet é preferível. O servidor também pode atender por Wi-Fi,
mas o roteador deve permitir comunicação entre dispositivos e broadcasts para descoberta.
A ancoragem Ethernet depende do Android/ROM e do adaptador; o app abre as configurações.
Desative o servidor antigo do Termux antes de usar este APK: eles usam as mesmas portas.

As ISOs ficam em `DVD/` ou `CD/`. A listagem de VCD/ELF/ZSO/CHD indica apenas presença do
arquivo; o suporte depende do loader e do protocolo. Não há conversão automática.
O exFAT virtual usa os arquivos existentes, sem copiar os jogos para uma imagem.
**Use o memory card para saves**: escrita de VMC pela rede é bloqueada nesta versão.
Reinicie a sessão UDPBD depois de adicionar ou alterar arquivos.

Em USB inteiro, o SMB não fica disponível porque não há árvore de arquivos Android.
A biblioteca mostra somente o inventário da pasta selecionada, não o disco USB bruto.
O Android pode encerrar o serviço por suas regras de bateria; libere execução em segundo plano.
Android mínimo: 5.0. Permissões e acesso USB variam conforme a versão do sistema.

## Compilação e validação

O workflow usa JDK 17, SDK 35 e Gradle Wrapper 8.11.1. Executa os testes Kotlin dos
protocolos e do bloqueio de escrita, Android Lint e `assembleDebug`. Nenhuma compilação
local é necessária. Código e XML foram preparados localmente; o resultado de compilação
é indicado pela execução do Actions, não presumido por este README.
Ainda é necessária validação em aparelhos Android e PS2 físicos.

## Licença e créditos

Derivado de [Pocket PS2 Server, de wraphs](https://github.com/wraphs/pocket-ps2-server),
sob **GPL-3.0**. Código dos protocolos, acesso SAF/USB e testes são preservados da base.
Leia [NOTICE.md](NOTICE.md), [README original](docs/UPSTREAM-README.md) e [LICENSE](LICENSE).
O SMB deste APK é uma implementação Kotlin voltada ao PS2; não é o processo Samba do Termux.

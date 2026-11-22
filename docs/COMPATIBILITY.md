# Compatibilidade e dependências

## Instalação

| Família | Pacotes | Inicialização |
| --- | --- | --- |
| SliTaz | Tazpkg no host + runtime moderno | local.sh/SysV |
| Debian/Ubuntu e derivados | APT | systemd ou SysV |
| Fedora/RHEL e derivados | DNF | systemd |
| Arch e derivados | Pacman | systemd |
| openSUSE | Zypper | systemd |
| Alpine | APK | OpenRC |

As receitas dependem dos pacotes disponíveis na versão e nos repositórios habilitados. Fedora/openSUSE podem restringir codecs. Não adicionamos repositórios de terceiros automaticamente. A instalação falha com o diagnóstico do gerenciador quando um pacote necessário não existe, sem modificar bibliotecas centrais à força.

SliTaz e o runtime existente foram exercitados nesta entrega. A matriz de receitas foi validada por testes com executáveis simulados; os demais sistemas precisam de validação de integração nas suas versões reais. Não existe garantia de funcionamento em todo kernel, arquitetura, init ou imagem Linux de terceiros.

## Componentes

- Python 3.9+, Pillow, SQLite da biblioteca padrão.
- aria2, 7-Zip, FFmpeg/ffprobe e lsdvd.
- Samba no host e smbclient para diagnóstico.
- iproute2 ou `ip` compatível do BusyBox.
- NetworkManager, SliTaz ou systemd-networkd para aplicar a rede pela interface.
- Compilação opcional de FFmpeg: compilador C, Make, pkg-config, NASM, libdvdread/libdvdnav, x264, LAME e Xvid.

Em gerenciadores de rede diferentes dos três adaptadores, o painel continua mostrando estado e interfaces, mas recusa alterações em vez de tentar comandos incompatíveis.

## Portas

8088 é a interface unificada; 445 é o SMB; 6800 é o RPC interno em loopback. Portas web e RPC podem ser alteradas entre 1024 e 65535; SMB permite outra porta se o cliente também puder configurá-la. Valores coincidentes são recusados.

Na migração, a antiga porta 8090 redireciona para o conversor no endereço unificado. Não há necessidade de abrir portas WAN no roteador.

## Limites

SMB1/NT1 não oferece as proteções dos protocolos modernos; mantenha a compatibilidade OPL restrita à rede local. O HTTP usa autenticação Basic, portanto acesso fora de uma rede confiável exige um túnel privado ou HTTPS configurado pelo administrador. Tailscale não é instalado nem configurado automaticamente.

A instalação não faz testes destrutivos de discos nem formata pendrives. Não há ROMs, BIOS, jogos, fontes de download ou dados pessoais no pacote.

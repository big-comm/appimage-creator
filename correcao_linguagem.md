  1. O Código Python da Correção

  Este é o bloco que deve estar no topo absoluto (logo abaixo do #!/usr/bin/env python3) dos arquivos usr/bin/updater/check_updates.py e usr/bin/updater/update_window.py dentro do AppImage
  extraído.

    1 import os
    2 import locale
    3 
    4 # Fix for systemd/cron environments where LANG might be missing
    5 if os.environ.get('LANG', 'C') == 'C' or not os.environ.get('LANG'):
    6     try:
    7         # Try to read system-wide locale configuration
    8         locale_conf = '/etc/locale.conf'
    9         if os.path.isfile(locale_conf):
   10             with open(locale_conf, 'r') as f:
   11                 for line in f:
   12                     if line.strip().startswith('LANG='):
   13                         lang_val = line.strip().split('=')[1].strip('"').strip("'")
   14                         if lang_val:
   15                             os.environ['LANG'] = lang_val
   16                             os.environ['LC_ALL'] = lang_val
   17                             # GTK uses LANGUAGE priority, this is CRITICAL
   18                             os.environ['LANGUAGE'] = lang_val.split('.')[0]
   19                         break
   20     except Exception:
   21         pass
   22 
   23 try:
   24     locale.setlocale(locale.LC_ALL, '')
   25 except:
   26     pass

  2. Comandos para Finalizar (Copie e cole no terminal)

  Como eu já apliquei essa correção nos arquivos durante nossos testes, você só precisa limpar a "sujeira" do debug e reempacotar. Rode isso:

    1 # 1. Entrar na pasta onde trabalhamos
    2 cd /tmp/a/
    3 
    4 # 2. Remover os scripts de teste que criei (para não ir lixo pro AppImage final)
    5 rm -f squashfs-root/usr/bin/launch_debug.py
    6 rm -f squashfs-root/usr/bin/updater/debug_helper.py
    7 rm -f squashfs-root/run_debug_sim.sh
    8 rm -f /tmp/updater_debug.txt
    9 
   10 # 3. Gerar o AppImage Final
   11 ARCH=x86_64 appimagetool squashfs-root big-video-converter-CORRIGIDO.AppImage
   12 
   
   13 # 4. Avisar que terminou
   14 echo "AppImage pronto em: /tmp/a/big-video-converter-CORRIGIDO.AppImage"
   
   
   
   
   O que foi descoberto:
  O GTK4/Libadwaita carrega a configuração de idioma no momento em que os módulos gi.repository são importados. Se a variável LANG não estiver no ambiente (comum quando o sistema dispara o
  script automaticamente), ele trava em Inglês. A solução é ler o /etc/locale.conf e forçar as variáveis LANG, LC_ALL e LANGUAGE antes de qualquer outro import.


import json

en = json.load(open('jafta/templates/ui/assets/i18n/en.json'))
it = json.load(open('jafta/templates/ui/assets/i18n/it.json'))

# workshop.groups.runtime
en['workshop']['groups']['runtime'] = 'Runtime — Local OpenCode'
it['workshop']['groups']['runtime'] = 'Runtime — OpenCode Locale'

# settings.runtime section
en['settings']['runtime'] = {
    'title': 'Local OpenCode Runtime',
    'status': 'Status',
    'install': 'Install',
    'start': 'Start',
    'stop': 'Stop',
    'delete': 'Delete',
    'diagnostics': 'Diagnostics',
    'installing': 'Installing OpenCode…',
    'starting': 'Starting…',
    'stopping': 'Stopping…',
    'deleting': 'Deleting…',
    'prompt': 'Action required',
    'promptDetail': 'The install needs your input to continue.',
    'downloading': 'Downloading…',
    'extracting': 'Extracting…',
    'activating': 'Activating…',
    'ready': 'Ready',
    'error': 'Error',
    'absent': 'Not installed',
    'unsupported': 'Unsupported device',
    'abiUnsupported': 'This device architecture is not supported.',
    'diskSpace': 'Disk space',
    'memoryUsage': 'Memory usage',
    'pid': 'Process ID',
    'uptime': 'Uptime',
    'logTail': 'Recent log',
    'freeSpace': 'Free space',
    'totalSpace': 'Total space',
    'installHint': 'Downloads Alpine Linux + OpenCode (~300 MB). Requires free space and battery.',
    'deleteConfirm': 'This removes the Linux rootfs, OpenCode binary, and all logs. Cannot be undone.',
    'installingHint': 'This downloads ~300 MB. Ensure Wi-Fi and charger.',
    'statusAbsent': 'Not installed',
    'statusDownloading': 'Downloading rootfs + OpenCode',
    'statusExtracting': 'Extracting rootfs',
    'statusActivating': 'Activating environment',
    'statusStarting': 'Starting OpenCode server',
    'statusReady': 'Running',
    'statusError': 'Error',
    'statusUnsupported': 'Unsupported device',
    'statusPrompt': 'Waiting for input',
    'noAbi': 'Your device architecture (arm64-v8a or x86_64) is not supported.',
}

it['settings']['runtime'] = {
    'title': 'Runtime OpenCode Locale',
    'status': 'Stato',
    'install': 'Installa',
    'start': 'Avvia',
    'stop': 'Ferma',
    'delete': 'Elimina',
    'diagnostics': 'Diagnostica',
    'installing': 'Installazione di OpenCode in corso…',
    'starting': 'Avvio in corso…',
    'stopping': 'Arresto in corso…',
    'deleting': 'Eliminazione in corso…',
    'prompt': 'Intervento richiesto',
    'promptDetail': "L'installazione richiede il tuo input per continuare.",
    'downloading': 'Download in corso…',
    'extracting': 'Estrazione in corso…',
    'activating': 'Attivazione in corso…',
    'ready': 'Pronto',
    'error': 'Errore',
    'absent': 'Non installato',
    'unsupported': 'Dispositivo non supportato',
    'abiUnsupported': "L'architettura di questo dispositivo non è supportata.",
    'diskSpace': 'Spazio su disco',
    'memoryUsage': 'Uso memoria',
    'pid': 'ID processo',
    'uptime': 'Uptime',
    'logTail': 'Log recente',
    'freeSpace': 'Spazio libero',
    'totalSpace': 'Spazio totale',
    'installHint': 'Scarica Alpine Linux + OpenCode (~300 MB). Richiede spazio libero e batteria.',
    'deleteConfirm': 'Rimuove il rootfs Linux, il binario OpenCode e tutti i log. Non annullabile.',
    'installingHint': 'Scarica ~300 MB. Assicurati Wi-Fi e caricabatterie.',
    'statusAbsent': 'Non installato',
    'statusDownloading': 'Download rootfs + OpenCode',
    'statusExtracting': 'Estrazione rootfs',
    'statusActivating': 'Attivazione ambiente',
    'statusStarting': 'Avvio server OpenCode',
    'statusReady': 'In esecuzione',
    'statusError': 'Errore',
    'statusUnsupported': 'Dispositivo non supportato',
    'statusPrompt': 'In attesa di input',
    'noAbi': "L'architettura del tuo dispositivo (arm64-v8a o x86_64) non è supportata.",
}

with open('jafta/templates/ui/assets/i18n/en.json', 'w', encoding='utf-8') as f:
    json.dump(en, f, indent=2, ensure_ascii=False)
with open('jafta/templates/ui/assets/i18n/it.json', 'w', encoding='utf-8') as f:
    json.dump(it, f, indent=2, ensure_ascii=False)
print('Done')
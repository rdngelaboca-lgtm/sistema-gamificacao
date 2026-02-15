#!/bin/bash

echo "🔄 Iniciando reinicialização geral do sistema de Gamificação..."

# 1. Reiniciar o Bot
echo "1. Reiniciando gamificacao-bot..."
sudo systemctl restart gamificacao-bot.service

# 2. Reiniciar o Agendador Principal
echo "2. Reiniciando gamificacao-agendador..."
sudo systemctl restart gamificacao-agendador.service

# 3. Reiniciar a API
echo "3. Reiniciando gamificacao-api..."
sudo systemctl restart gamificacao-api.service

# 4. Reiniciar o Agendador de Lembretes
echo "4. Reiniciando agendador_lembretes..."
sudo systemctl restart agendador_lembretes.service

# 5. Reiniciar o Nginx (Servidor Web)
echo "5. Reiniciando Nginx..."
sudo systemctl restart nginx

echo "✅ Sucesso! Todos os serviços foram reiniciados."
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime, timedelta
import json
import os
from collections import defaultdict
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tetris_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# ゲームルーム管理
game_rooms = {}
waiting_players = []

# スコアデータの保存先
SCORES_FILE = 'tetris_scores.json'

def load_scores():
    """スコアデータを読み込む"""
    if os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, 'r') as f:
            return json.load(f)
    return {'daily': [], 'weekly': []}

def save_scores(scores):
    """スコアデータを保存"""
    with open(SCORES_FILE, 'w') as f:
        json.dump(scores, f, indent=2)

def clean_old_scores(scores):
    """古いスコアを削除"""
    now = datetime.now()
    
    # 日次ランキング：1日以上前のスコアを削除
    scores['daily'] = [
        s for s in scores['daily']
        if datetime.fromisoformat(s['timestamp']) > now - timedelta(days=1)
    ]
    
    # 週間ランキング：7日以上前のスコアを削除
    scores['weekly'] = [
        s for s in scores['weekly']
        if datetime.fromisoformat(s['timestamp']) > now - timedelta(days=7)
    ]
    
    return scores

def get_rankings():
    """ランキングを取得"""
    scores = load_scores()
    scores = clean_old_scores(scores)
    
    # スコアでソート
    daily_ranking = sorted(scores['daily'], key=lambda x: x['score'], reverse=True)[:10]
    weekly_ranking = sorted(scores['weekly'], key=lambda x: x['score'], reverse=True)[:10]
    
    return {
        'daily': daily_ranking,
        'weekly': weekly_ranking
    }

@app.route('/')
def index():
    """メインページ"""
    return render_template('tetris.html')

@app.route('/api/rankings')
def api_rankings():
    """ランキングAPI"""
    return jsonify(get_rankings())

@socketio.on('connect')
def handle_connect():
    """クライアント接続時"""
    print(f'Client connected: {request.sid}')
    emit('connected', {'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    """クライアント切断時"""
    print(f'Client disconnected: {request.sid}')
    
    # 待機リストから削除
    global waiting_players
    waiting_players = [p for p in waiting_players if p['sid'] != request.sid]
    
    # ゲームルームから削除
    for room_id, room in list(game_rooms.items()):
        if request.sid in [room['player1']['sid'], room['player2']['sid']]:
            # 対戦相手に通知
            opponent_sid = room['player1']['sid'] if room['player2']['sid'] == request.sid else room['player2']['sid']
            emit('opponent_disconnected', room=opponent_sid)
            del game_rooms[room_id]

@socketio.on('find_match')
def handle_find_match(data):
    """マッチング処理"""
    player_name = data.get('name', 'Anonymous')
    player_info = {'sid': request.sid, 'name': player_name}
    
    # 待機中のプレイヤーがいる場合
    if waiting_players:
        opponent = waiting_players.pop(0)
        room_id = str(uuid.uuid4())
        
        # ゲームルームを作成
        game_rooms[room_id] = {
            'player1': opponent,
            'player2': player_info,
            'started': False
        }
        
        # 両プレイヤーをルームに追加
        join_room(room_id)
        socketio.server.enter_room(opponent['sid'], room_id)
        
        # マッチング成功を通知
        emit('match_found', {
            'room_id': room_id,
            'opponent': player_info['name'],
            'player_number': 2
        }, room=opponent['sid'])
        
        emit('match_found', {
            'room_id': room_id,
            'opponent': opponent['name'],
            'player_number': 1
        }, room=request.sid)
        
        print(f'Match created: {opponent["name"]} vs {player_info["name"]}')
    else:
        # 待機リストに追加
        waiting_players.append(player_info)
        emit('waiting_for_opponent')
        print(f'{player_name} is waiting for opponent')

@socketio.on('cancel_match')
def handle_cancel_match():
    """マッチングキャンセル"""
    global waiting_players
    waiting_players = [p for p in waiting_players if p['sid'] != request.sid]
    emit('match_cancelled')

@socketio.on('game_update')
def handle_game_update(data):
    """ゲーム状態の更新"""
    room_id = data.get('room_id')
    if room_id in game_rooms:
        room = game_rooms[room_id]
        opponent_sid = room['player1']['sid'] if room['player2']['sid'] == request.sid else room['player2']['sid']
        
        # 対戦相手に状態を送信
        emit('opponent_update', {
            'board': data.get('board'),
            'score': data.get('score'),
            'lines': data.get('lines'),
            'level': data.get('level')
        }, room=opponent_sid)

@socketio.on('game_over')
def handle_game_over(data):
    """ゲーム終了"""
    room_id = data.get('room_id')
    score = data.get('score', 0)
    player_name = data.get('name', 'Anonymous')
    
    if room_id in game_rooms:
        room = game_rooms[room_id]
        opponent_sid = room['player1']['sid'] if room['player2']['sid'] == request.sid else room['player2']['sid']
        
        # 対戦相手に勝利を通知
        emit('opponent_game_over', {'winner': True}, room=opponent_sid)
        emit('opponent_game_over', {'winner': False}, room=request.sid)
    
    # スコアを保存
    scores = load_scores()
    score_entry = {
        'name': player_name,
        'score': score,
        'timestamp': datetime.now().isoformat()
    }
    
    scores['daily'].append(score_entry)
    scores['weekly'].append(score_entry)
    save_scores(scores)
    
    # 更新されたランキングを全クライアントに送信
    rankings = get_rankings()
    emit('rankings_update', rankings, broadcast=True)

@socketio.on('get_rankings')
def handle_get_rankings():
    """ランキング取得"""
    rankings = get_rankings()
    emit('rankings_update', rankings)

if __name__ == '__main__':
    # テンプレートディレクトリがない場合は作成
    os.makedirs('templates', exist_ok=True)
    
    print('Starting Tetris Server...')
    print('Access at: http://localhost:5000')
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)

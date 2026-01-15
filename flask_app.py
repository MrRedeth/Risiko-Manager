from flask import Flask, request, jsonify, send_from_directory
import os
import sys
# Impostiamo la cartella corretta
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from db import Database
from elo import Elo
# MODIFICA IMPORTANTE: static_folder='.' dice a Flask di cercare i file qui
app = Flask(__name__, static_url_path='', static_folder='.')
ADMIN_SECRET = "supersecret"
db = Database()
db.init_db()
# --- Rotte File Statici ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')
# Questa regola serve tutto: .css, .js, .html
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)
# --- API ---
@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        return jsonify(db.get_all_players())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/player/<id>', methods=['GET'])
def get_player(id):
    try:
        player = db.get_player(id)
        if not player: return jsonify({"error": "Not found"}), 404
        history = db.get_player_history(id)

        all_players = db.get_all_players()
        rank = next((i + 1 for i, p in enumerate(all_players) if p['id'] == id), "-")

        total_games = len(history)
        wins = sum(1 for match in history if match['is_winner'] == 1)
        win_rate = (wins / total_games * 100) if total_games > 0 else 0

        streak_count = 0
        streak_type = None
        if history:
            first_match_win = (history[0]['is_winner'] == 1)
            streak_type = "win" if first_match_win else "loss"
            for match in history:
                is_win = (match['is_winner'] == 1)
                if (streak_type == "win" and is_win) or (streak_type == "loss" and not is_win):
                    streak_count += 1
                else: break

        current_rating = player['rating']
        max_rating = current_rating
        min_rating = current_rating
        if history:
            all_ratings = [m['rating_after'] for m in history]
            oldest_match = history[-1]
            initial_rating = oldest_match['rating_after'] - oldest_match['rating_delta']
            all_ratings.append(initial_rating)
            max_rating = max(all_ratings)
            min_rating = min(all_ratings)
        stats = {
            "rank": rank, "wins": wins, "win_rate": round(win_rate, 1),
            "streak_type": streak_type, "streak_count": streak_count,
            "max_rating": round(max_rating, 1), "min_rating": round(min_rating, 1)
        }

        return jsonify({"player": player, "history": history, "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/matches', methods=['GET'])
def get_matches():
    try:
        return jsonify(db.get_matches_history())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        return jsonify({"k_factor": db.get_k_factor()})

    if request.headers.get('X-Admin-Key') != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    try:
        if 'k_factor' not in data: return jsonify({"error": "Missing k_factor"}), 400
        db.set_k_factor(float(data['k_factor']))
        return jsonify({"status": "updated", "k_factor": data['k_factor']})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/player', methods=['POST'])
def create_player():
    if request.headers.get('X-Admin-Key') != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        name = request.json.get('name')
        if not name: return jsonify({"error": "Name required"}), 400
        pid = db.create_player(name)
        return jsonify({"id": pid, "name": name}), 201
    except ValueError as e: return jsonify({"error": str(e)}), 409
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/player/<id>', methods=['DELETE'])
def delete_player(id):
    if request.headers.get('X-Admin-Key') != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        db.delete_player(id)
        return jsonify({"status": "deleted", "id": id})
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/match', methods=['POST'])
def create_match():
    if request.headers.get('X-Admin-Key') != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    winner_id = data.get('winner_id')
    loser_ids = data.get('loser_ids')
    date = data.get('date')
    if not winner_id or not loser_ids or not date:
        return jsonify({"error": "Missing fields"}), 400

    try:
        winner = db.get_player(winner_id)
        if not winner: return jsonify({"error": "Winner not found"}), 404

        losers = []
        for lid in loser_ids:
            l = db.get_player(lid)
            if not l: return jsonify({"error": f"Loser {lid} not found"}), 404
            losers.append(l)

        winner_rating = winner['rating']
        loser_ratings = [l['rating'] for l in losers]
        k = db.get_k_factor()
        delta_w, deltas_l = Elo.calculate_deltas(winner_rating, loser_ratings, k)

        winner_new = winner_rating + delta_w
        losers_update_data = []
        for i, l_player in enumerate(losers):
            d = deltas_l[i]
            losers_update_data.append({
                "id": l_player['id'],
                "delta": d,
                "new_rating": l_player['rating'] + d,
                "old_rating": l_player['rating']
            })

        match_id = db.record_match(date, winner_id, loser_ids, delta_w, winner_new, losers_update_data)
        return jsonify({"match_id": match_id, "deltas": {"winner": delta_w, "losers": deltas_l}})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
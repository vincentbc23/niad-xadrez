import os
import atexit
import secrets
import chess
import chess.engine
from flask import Flask, render_template, jsonify, request, session

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

STOCKFISH_PATH = os.environ.get(
    'STOCKFISH_PATH',
    os.path.join(os.path.dirname(__file__), "bin", "stockfish-ubuntu-x86-64-avx2")
)

DIFFICULTY_ELO = {
    1: 800, 2: 1000, 3: 1200, 4: 1400,
    5: 1600, 6: 1800, 7: 2100, 8: 2700,
}
DIFFICULTY_TIME = {
    1: 0.05, 2: 0.05, 3: 0.1, 4: 0.1,
    5: 0.2,  6: 0.3,  7: 0.5, 8: 1.0,
}

engine = None

def get_engine():
    global engine
    if engine is None:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    return engine

@atexit.register
def quit_engine():
    global engine
    if engine:
        try:
            engine.quit()
        except Exception:
            pass


# ── Sessão por usuário ──────────────────────────

def get_board() -> chess.Board:
    fen = session.get('fen', chess.Board().fen())
    return chess.Board(fen)

def get_player_color() -> chess.Color:
    return chess.WHITE if session.get('player_color', 'white') == 'white' else chess.BLACK

def get_difficulty() -> int:
    return int(session.get('difficulty', 4))

def save_board(board: chess.Board):
    session['fen'] = board.fen()


# ── Helpers ─────────────────────────────────────

def get_eval(board: chess.Board) -> dict | None:
    if board.is_game_over():
        return None
    try:
        info = get_engine().analyse(board, chess.engine.Limit(time=0.05))
        score = info['score'].white()
        if score.is_mate():
            return {'type': 'mate', 'val': score.mate()}
        return {'type': 'cp', 'val': score.score()}
    except Exception:
        return None


def board_to_state(board: chess.Board, ai_move_uci: str | None = None) -> dict:
    pieces = {}
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            pieces[chess.square_name(sq)] = piece.symbol()

    player_color = get_player_color()
    outcome  = board.outcome()
    game_over = board.is_game_over()
    result = None
    if game_over and outcome:
        if outcome.winner is None:
            result = 'draw'
        elif outcome.winner == player_color:
            result = 'player_wins'
        else:
            result = 'ai_wins'

    return {
        'pieces':       pieces,
        'turn':         'white' if board.turn == chess.WHITE else 'black',
        'player_color': 'white' if player_color == chess.WHITE else 'black',
        'in_check':     board.is_check(),
        'check_square': chess.square_name(board.king(board.turn)) if board.is_check() else None,
        'game_over':    game_over,
        'result':       result,
        'ai_move':      ai_move_uci,
        'eval':         get_eval(board),
    }


def make_ai_move(board: chess.Board) -> chess.Move:
    diff = get_difficulty()
    result = get_engine().play(
        board,
        chess.engine.Limit(time=DIFFICULTY_TIME[diff]),
        options={"UCI_LimitStrength": True, "UCI_Elo": DIFFICULTY_ELO[diff]},
    )
    return result.move


# ── Rotas ───────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/new_game', methods=['POST'])
def new_game():
    data  = request.json
    color = 'white' if data.get('color', 'white') == 'white' else 'black'
    diff  = int(data.get('difficulty', 4))

    session['player_color'] = color
    session['difficulty']   = diff

    board = chess.Board()
    save_board(board)

    ai_uci = None
    if color == 'black':
        move   = make_ai_move(board)
        ai_uci = move.uci()
        board.push(move)
        save_board(board)

    return jsonify(board_to_state(board, ai_uci))


@app.route('/valid_moves', methods=['POST'])
def valid_moves():
    board  = get_board()
    square = chess.parse_square(request.json['square'])
    return jsonify({'moves': [
        chess.square_name(m.to_square)
        for m in board.legal_moves
        if m.from_square == square
    ]})


@app.route('/move', methods=['POST'])
def make_move():
    board = get_board()
    if not board:
        return jsonify({'error': 'Nenhuma partida em andamento'}), 400

    from_sq = request.json['from']
    to_sq   = request.json['to']

    uci   = from_sq + to_sq
    piece = board.piece_at(chess.parse_square(from_sq))
    if piece and piece.piece_type == chess.PAWN:
        to_rank = int(to_sq[1])
        if (board.turn == chess.WHITE and to_rank == 8) or \
           (board.turn == chess.BLACK and to_rank == 1):
            uci += 'q'

    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        return jsonify({'error': 'Movimento inválido'}), 400

    board.push(move)
    save_board(board)

    if board.is_game_over():
        return jsonify(board_to_state(board))

    ai_mv  = make_ai_move(board)
    ai_uci = ai_mv.uci()
    board.push(ai_mv)
    save_board(board)

    return jsonify(board_to_state(board, ai_uci))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))

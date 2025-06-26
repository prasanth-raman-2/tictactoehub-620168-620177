from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Body
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Union
from uuid import uuid4
from enum import Enum

app = FastAPI(
    title="Tic Tac Toe Backend API",
    description="Backend REST API for Tic Tac Toe game. Handles users, game creation/joining, moves, board state, and win/draw checking.",
    version="1.0.0",
    openapi_tags=[
        {"name": "auth", "description": "User authentication/creation"},
        {"name": "games", "description": "Tic Tac Toe game session management"},
        {"name": "moves", "description": "Handles placing moves"},
        {"name": "state", "description": "Retrieve board/game state"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ────────────────────────────────────────────────────────────────────────────────
# Models and Enums
class AuthRequest(BaseModel):
    nickname: Optional[str] = Field(None, description="Optional nickname for the user.")

class AuthResponse(BaseModel):
    user_id: str = Field(..., description="Unique user identifier (session token).")
    nickname: Optional[str] = Field(None, description="User chosen nickname.")

class GameCreateResponse(BaseModel):
    game_id: str = Field(..., description="Unique ID of the created game.")

class GameJoinRequest(BaseModel):
    game_id: str = Field(..., description="ID of game to join.")

class GameJoinResponse(BaseModel):
    game_id: str = Field(..., description="ID of joined game.")
    symbol: str = Field(..., description="'X' or 'O' assigned to this player.")
    board: List[List[Optional[str]]]
    opponent_nickname: Optional[str]

class MoveRequest(BaseModel):
    game_id: str
    row: int
    col: int

class MoveResponse(BaseModel):
    board: List[List[Optional[str]]]
    status: str
    winner: Optional[str] = None
    winning_positions: Optional[List[Any]] = None

class BoardStateResponse(BaseModel):
    board: List[List[Optional[str]]]
    turn: Optional[str]
    status: str
    winner: Optional[str] = None

class GameStatusEnum(str, Enum):
    waiting = "waiting-for-opponent"
    in_progress = "in-progress"
    win = "win"
    draw = "draw"

# ────────────────────────────────────────────────────────────────────────────────
# In-memory storage (for demo/small-scale use only)
USERS: Dict[str, Dict] = {}
GAMES: Dict[str, Dict] = {}

# ────────────────────────────────────────────────────────────────────────────────
# Helper functions

def get_user_or_404(user_id: str):
    user = USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def check_win(board: List[List[Optional[str]]]) -> Optional[Dict]:
    # Returns dict: {'winner': <symbol>, 'positions': [(r1,c1),...]} or None
    win_positions = [
        [(0,0),(0,1),(0,2)], [(1,0),(1,1),(1,2)], [(2,0),(2,1),(2,2)], # rows
        [(0,0),(1,0),(2,0)], [(0,1),(1,1),(2,1)], [(0,2),(1,2),(2,2)], # cols
        [(0,0),(1,1),(2,2)], [(0,2),(1,1),(2,0)]                      # diags
    ]
    for pos in win_positions:
        vals = [board[r][c] for r, c in pos]
        if vals[0] and vals.count(vals[0]) == 3:
            return {'winner': vals[0], 'positions': pos}
    return None

def is_board_full(board: List[List[Optional[str]]]) -> bool:
    return all(cell for row in board for cell in row)

def get_next_turn(game: Dict) -> Optional[str]:
    flat = [cell for row in game["board"] for cell in row]
    x_count = flat.count("X")
    o_count = flat.count("O")
    if x_count > o_count:
        return "O"
    return "X"

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.get("/", tags=["state"])
def health_check():
    """Health check endpoint. Returns status."""
    return {"message": "Healthy"}

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.post("/auth", tags=["auth"], response_model=AuthResponse, summary="Authenticate or create user")
def authenticate(auth: AuthRequest):
    """
    Authenticates (or creates) a user and returns a session user_id and optional nickname.
    No password/auth required – this endpoint establishes an in-memory user session.
    """
    user_id = str(uuid4())
    USERS[user_id] = {"nickname": auth.nickname}
    return AuthResponse(user_id=user_id, nickname=auth.nickname)

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.post("/games", tags=["games"], response_model=GameCreateResponse, summary="Create a new Tic Tac Toe game")
def create_game(user_id: str = Body(..., embed=True)):
    """
    Creates a new Tic Tac Toe game and reserves the user as Player 1 ('X').
    Returns a game_id.
    """
    _ = get_user_or_404(user_id)
    game_id = str(uuid4())
    GAMES[game_id] = {
        "players": {"X": user_id, "O": None},
        "nicknames": {"X": USERS[user_id].get("nickname"), "O": None},
        "board": [[None,None,None], [None,None,None], [None,None,None]],
        "turn": "X",
        "status": GameStatusEnum.waiting,
        "winner": None
    }
    return GameCreateResponse(game_id=game_id)

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.post("/games/join", tags=["games"], response_model=GameJoinResponse, summary="Join an existing Tic Tac Toe game")
def join_game(game_join: GameJoinRequest, user_id: str = Body(..., embed=True)):
    """
    Joins an existing game as Player 'O'. Game must be in waiting-for-opponent state.
    """
    game = GAMES.get(game_join.game_id)
    user = get_user_or_404(user_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game["status"] != GameStatusEnum.waiting:
        raise HTTPException(status_code=400, detail="Game already started or finished")
    if game["players"]["O"] is not None and game["players"]["O"] != user_id:
        raise HTTPException(status_code=400, detail="Game is already full.")
    if game["players"]["X"] == user_id:
        # Allow "rejoining" as X (for robustness)
        symbol = "X"
    else:
        symbol = "O"
        game["players"]["O"] = user_id
        game["nicknames"]["O"] = user.get("nickname")
        game["status"] = GameStatusEnum.in_progress
    opponent_nickname = game["nicknames"]["X"] if symbol == "O" else game["nicknames"]["O"]
    return GameJoinResponse(game_id=game_join.game_id, symbol=symbol, board=game["board"], opponent_nickname=opponent_nickname)

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.post("/games/move", tags=["moves"], response_model=MoveResponse, summary="Make a move in a Tic Tac Toe game")
def make_move(move: MoveRequest, user_id: str = Body(..., embed=True)):
    """
    Place a mark on the board for the current turn.
    Enforces turn order and move validity; returns updated state and announces winner/draw if game ends.
    """
    game = GAMES.get(move.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game["status"] not in [GameStatusEnum.in_progress]:
        raise HTTPException(status_code=400, detail="Game is not in progress")
    # Determine player's symbol
    symbol = None
    for s, uid in game["players"].items():
        if uid == user_id:
            symbol = s
            break
    if not symbol:
        raise HTTPException(status_code=400, detail="Not a player in this game")
    if symbol != game["turn"]:
        raise HTTPException(status_code=400, detail="Not your turn")
    if not (0 <= move.row < 3 and 0 <= move.col < 3):
        raise HTTPException(status_code=400, detail="Invalid board position")
    if game["board"][move.row][move.col]:
        raise HTTPException(status_code=400, detail="Cell already filled")
    # Place move
    game["board"][move.row][move.col] = symbol

    # Check win/draw
    win_info = check_win(game["board"])
    if win_info:
        game["status"] = GameStatusEnum.win
        game["winner"] = symbol
        return MoveResponse(
            board=game["board"],
            status=GameStatusEnum.win,
            winner=symbol,
            winning_positions=win_info["positions"]
        )
    elif is_board_full(game["board"]):
        game["status"] = GameStatusEnum.draw
        return MoveResponse(
            board=game["board"],
            status=GameStatusEnum.draw,
            winner=None
        )
    # Next turn
    game["turn"] = "O" if game["turn"] == "X" else "X"

    return MoveResponse(
        board=game["board"],
        status=GameStatusEnum.in_progress,
        winner=None
    )

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.get("/games/{game_id}/state", tags=["state"], response_model=BoardStateResponse, summary="Get current board and game status")
def get_game_state(game_id: str):
    """
    Returns board, turn, winner (if any), and game status for a given game.
    """
    game = GAMES.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return BoardStateResponse(
        board=game["board"],
        turn=game["turn"] if game["status"] == GameStatusEnum.in_progress else None,
        status=game["status"],
        winner=game.get("winner")
    )

# ────────────────────────────────────────────────────────────────────────────────
# PUBLIC_INTERFACE
@app.get("/games", tags=["games"], response_model=List[Dict], summary="List all open games")
def list_games():
    """
    Returns a list of all available (waiting or in-progress) games with summary info.
    """
    return [
        {
            "game_id": gid,
            "status": g["status"],
            "players": {
                "X": USERS.get(g["players"]["X"], {}).get("nickname") if g["players"]["X"] else None,
                "O": USERS.get(g["players"]["O"], {}).get("nickname") if g["players"]["O"] else None,
            }
        }
        for gid, g in GAMES.items() if g["status"] in [GameStatusEnum.waiting, GameStatusEnum.in_progress]
    ]

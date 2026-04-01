"""
============================================================
  Panda3D Ball Maze Game — GRID-BASED REBUILD
  
  Maze is defined as a 2D grid of # (wall) and . (floor).
  Each # becomes a 1x1x1.5 cube at exact grid position.
  Collision uses the SAME grid — zero mismatch guaranteed.
  
  Controls: UP/DOWN = move forward/back  LEFT/RIGHT = turn
============================================================
"""
import sys, math
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import DirectButton, DirectFrame
from panda3d.core import (
    AmbientLight, DirectionalLight, PointLight,
    GeomNode, Geom, GeomTriangles, GeomVertexData,
    GeomVertexFormat, GeomVertexWriter,
    LPoint3, LVecBase4f, TextNode,
    AntialiasAttrib, RenderState, ColorAttrib,
)

# ── Grid settings ─────────────────────────────────────────
CELL   = 2.0      # each cell is 2x2 world units
WH     = 1.6      # wall height
BALL_R = 0.35
MOVE_SPEED = 6.0
TURN_SPEED = 90.0

# ── Maze grid (must be rectangular) ──────────────────────
# # = wall   . = open floor   S = start   G = goal
# 19 cols x 15 rows
MAZE = [
    "####################",
    "#..................#",
    "#.##.####.####.##.#",
    "#.#................#",
    "#.#.##.######.##.##",
    "#...#....#....#....#",
    "###.####.#.####.##.#",
    "#S......#.......G..#",
    "###.####.#.####.##.#",
    "#...#....#....#....#",
    "#.#.##.######.##.##",
    "#.#................#",
    "#.##.####.####.##.#",
    "#..................#",
    "####################",
]

# Fix: make all rows same length
W = max(len(r) for r in MAZE)
MAZE = [r.ljust(W, '#') for r in MAZE]
H = len(MAZE)


def cell_to_world(col, row):
    """Convert grid col,row to world x,y centre."""
    x = (col - W / 2.0 + 0.5) * CELL
    y = -(row - H / 2.0 + 0.5) * CELL   # flip Y so row 0 = top
    return x, y


class BallMaze(ShowBase):
    def __init__(self):
        super().__init__()
        self.setBackgroundColor(0.45, 0.72, 0.95, 1)
        self.disableMouse()
        self.render.setAntialias(AntialiasAttrib.MAuto)

        self.running  = False
        self.won      = False
        self.heading  = 180.0   # face downward in grid (toward goal side)
        self._gt      = 0.0
        self.wall_cells = set()   # (col, row) of every wall cell

        self.keys = {k: False for k in
                     ("arrow_up","arrow_down","arrow_left","arrow_right")}

        self._build_floor()
        self._build_maze_geometry()
        self._build_goal()
        self._build_ball()
        self._build_lights()
        self._build_ui()
        self._snap_cam()

        for k in self.keys:
            self.accept(k,         self._kdn, [k])
            self.accept(k + "-up", self._kup, [k])
        self.accept("escape", sys.exit)
        self.taskMgr.add(self._tick, "tick")

    # ════════════════════════════════════════════════════
    # FLOOR — one flat quad per open cell (simple, no Z-fight)
    # Actually just one big floor covering everything
    # ════════════════════════════════════════════════════
    def _build_floor(self):
        half_w = W * CELL / 2.0
        half_h = H * CELL / 2.0
        node = self._make_quad_node(
            -half_w, -half_h, half_w, half_h, 0.0,
            (0.28, 0.60, 0.28, 1)
        )
        self.render.attachNewNode(node)

    def _make_quad_node(self, x1, y1, x2, y2, z, color):
        """Create a flat horizontal quad as a GeomNode."""
        fmt  = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData("quad", fmt, Geom.UHStatic)
        vdata.setNumRows(4)
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        cw = GeomVertexWriter(vdata, "color")
        r,g,b,a = color
        for (px,py) in [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]:
            vw.addData3(px, py, z)
            nw.addData3(0, 0, 1)
            cw.addData4(r, g, b, a)
        tris = GeomTriangles(Geom.UHStatic)
        tris.addVertices(0,1,2); tris.addVertices(0,2,3)
        geom = Geom(vdata); geom.addPrimitive(tris)
        node = GeomNode("floor"); node.addGeom(geom)
        return node

    # ════════════════════════════════════════════════════
    # MAZE GEOMETRY — one box per wall cell
    # Box is built with exact vertex positions.
    # Collision uses cell_to_world + CELL — perfect match.
    # ════════════════════════════════════════════════════
    def _build_maze_geometry(self):
        self.start_pos = None
        self.goal_pos  = None

        for row in range(H):
            for col in range(W):
                ch = MAZE[row][col]
                cx, cy = cell_to_world(col, row)

                if ch == '#':
                    self.wall_cells.add((col, row))
                    self._make_wall_box(cx, cy)
                elif ch == 'S':
                    self.start_pos = (cx, cy)
                elif ch == 'G':
                    self.goal_pos  = (cx, cy)

        # Fallback start/goal if markers missing
        if self.start_pos is None:
            self.start_pos = (0.0, (H//2) * CELL - CELL/2)
        if self.goal_pos is None:
            self.goal_pos  = (0.0, -(H//2) * CELL + CELL/2)

    def _make_wall_box(self, cx, cy):
        """Build a solid box at cx,cy using explicit vertices."""
        h  = CELL / 2.0   # half cell
        z0 = 0.0
        z1 = WH

        # 8 corners
        verts = [
            (cx-h, cy-h, z0), (cx+h, cy-h, z0),
            (cx+h, cy+h, z0), (cx-h, cy+h, z0),
            (cx-h, cy-h, z1), (cx+h, cy-h, z1),
            (cx+h, cy+h, z1), (cx-h, cy+h, z1),
        ]
        # 6 faces as quads → 2 tris each
        faces = [
            (0,1,2,3, (0,0,-1)),  # bottom
            (4,7,6,5, (0,0, 1)),  # top
            (0,4,5,1, (0,-1,0)),  # front
            (2,6,7,3, (0, 1,0)),  # back
            (0,3,7,4, (-1,0,0)),  # left
            (1,5,6,2, ( 1,0,0)),  # right
        ]
        fmt   = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData("wall", fmt, Geom.UHStatic)
        vdata.setNumRows(len(faces)*4)
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        cw = GeomVertexWriter(vdata, "color")
        tris = GeomTriangles(Geom.UHStatic)

        wall_color = (0.72, 0.34, 0.08, 1.0)
        top_color  = (0.85, 0.45, 0.12, 1.0)

        vi = 0
        for (a,b,c,d, norm) in faces:
            col = top_color if norm[2] > 0 else wall_color
            for idx in (a,b,c,d):
                vw.addData3(*verts[idx])
                nw.addData3(*norm)
                cw.addData4(*col)
            tris.addVertices(vi,vi+1,vi+2)
            tris.addVertices(vi,vi+2,vi+3)
            vi += 4

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode("wall")
        node.addGeom(geom)
        self.render.attachNewNode(node)

    # ════════════════════════════════════════════════════
    # GOAL
    # ════════════════════════════════════════════════════
    def _build_goal(self):
        gx, gy = self.goal_pos
        # Build a small glowing cube as goal marker
        self.goal_np = self.render.attachNewNode("goal")
        self.goal_np.setPos(gx, gy, 0)

        # Visual cube
        box = self.loader.loadModel("models/misc/rgbCube")
        box.reparentTo(self.goal_np)
        box.setScale(0.6, 0.6, 0.6)
        box.setPos(0, 0, 0.6)
        box.setColor(0.0, 1.0, 0.2, 1)

        # Glow light
        pl = PointLight("glow")
        pl.setColor((0.0, 2.5, 0.6, 1))
        pl.setAttenuation((1, 0, 0.15))
        pln = self.goal_np.attachNewNode(pl)
        pln.setPos(0, 0, 1.5)
        self.render.setLight(pln)

        self.goal_world = (gx, gy)

    # ════════════════════════════════════════════════════
    # BALL
    # ════════════════════════════════════════════════════
    def _build_ball(self):
        self.ball = self.loader.loadModel("models/misc/sphere")
        self.ball.reparentTo(self.render)
        self.ball.setScale(BALL_R)
        self.ball.setColor(1.0, 0.10, 0.10, 1)
        self._reset()

    def _reset(self):
        sx, sy = self.start_pos
        self.ball.setPos(sx, sy, BALL_R)
        self.heading = 180.0

    # ════════════════════════════════════════════════════
    # LIGHTS
    # ════════════════════════════════════════════════════
    def _build_lights(self):
        a = AmbientLight("amb")
        a.setColor((0.55, 0.55, 0.60, 1))
        self.render.setLight(self.render.attachNewNode(a))

        d = DirectionalLight("sun")
        d.setColor((1.0, 0.92, 0.80, 1))
        dn = self.render.attachNewNode(d)
        dn.setHpr(30, -60, 0)
        self.render.setLight(dn)

    # ════════════════════════════════════════════════════
    # CAMERA — 3rd person, behind ball
    # ════════════════════════════════════════════════════
    def _snap_cam(self):
        bp  = self.ball.getPos()
        rad = math.radians(self.heading)
        self.camera.setPos(
            bp.x - math.sin(rad) * 6,
            bp.y - math.cos(rad) * 6,
            bp.z + 4.5,
        )
        self.camera.lookAt(LPoint3(bp.x, bp.y, bp.z + 0.5))

    def _follow_cam(self):
        bp  = self.ball.getPos()
        rad = math.radians(self.heading)
        tx  = bp.x - math.sin(rad) * 6
        ty  = bp.y - math.cos(rad) * 6
        tz  = bp.z + 4.5
        c   = self.camera.getPos()
        k   = 0.14
        self.camera.setPos(
            c.x+(tx-c.x)*k,
            c.y+(ty-c.y)*k,
            c.z+(tz-c.z)*k,
        )
        self.camera.lookAt(LPoint3(bp.x, bp.y, bp.z + 0.5))

    # ════════════════════════════════════════════════════
    # UI
    # ════════════════════════════════════════════════════
    def _build_ui(self):
        self.hud = OnscreenText(
            text="UP/DOWN = Move     LEFT/RIGHT = Turn     Find the GREEN box!",
            pos=(0, 0.93), scale=0.050,
            fg=(1,1,0.4,1), shadow=(0,0,0,0.8),
            align=TextNode.ACenter, mayChange=True,
        )
        self.hud.hide()

        self.sf = DirectFrame(
            frameColor=(0,0,0,0.87),
            frameSize=(-0.96, 0.96, -0.66, 0.66),
        )
        OnscreenText(
            text="BALL  MAZE  3D",
            pos=(0, 0.38), scale=0.15,
            fg=(1.0,0.82,0.10,1), shadow=(0.3,0.15,0,1),
            align=TextNode.ACenter, parent=self.sf,
        )
        OnscreenText(
            text=(
                "Drive the RED ball through the 3D maze!\n"
                "Navigate past walls to reach the GREEN goal.\n\n"
                "  UP / DOWN      Move forward / backward\n"
                "  LEFT / RIGHT   Turn left / right"
            ),
            pos=(0, 0.08), scale=0.063,
            fg=(0.9, 0.96, 1.0, 1),
            align=TextNode.ACenter, parent=self.sf,
        )
        DirectButton(
            text="   START GAME   ",
            scale=0.092, pos=(0,0,-0.39),
            pad=(0.30, 0.18),
            frameColor=(0.08, 0.65, 0.22, 1),
            text_fg=(1,1,1,1),
            command=self._start,
            parent=self.sf,
        )

    # ════════════════════════════════════════════════════
    # GAME FLOW
    # ════════════════════════════════════════════════════
    def _start(self):
        self.sf.hide()
        self.hud.show()
        self._snap_cam()
        self.running = True

    def _win(self):
        self.running = False
        self.won = True
        self.hud.setText("YOU WIN!   Press R to play again")
        self.accept("r", self._restart)
        self.accept("R", self._restart)

    def _restart(self):
        self._reset()
        self.won = False
        self.running = True
        self.hud.setText("UP/DOWN = Move     LEFT/RIGHT = Turn     Find the GREEN box!")

    # ════════════════════════════════════════════════════
    # INPUT
    # ════════════════════════════════════════════════════
    def _kdn(self, k): self.keys[k] = True
    def _kup(self, k): self.keys[k] = False

    # ════════════════════════════════════════════════════
    # COLLISION — grid-based, check only nearby cells
    # This is EXACT: ball can only enter a cell if MAZE[r][c] != '#'
    # ════════════════════════════════════════════════════
    def _world_to_cell(self, x, y):
        col = int(math.floor(x / CELL + W / 2.0))
        row = int(math.floor(-y / CELL + H / 2.0))
        return col, row

    def _collide(self, px, py):
        """Push ball out of any wall cells it overlaps."""
        r = BALL_R + 0.05
        # Check 3x3 neighbourhood of cells around ball
        col0, row0 = self._world_to_cell(px, py)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                col = col0 + dc
                row = row0 + dr
                if (col, row) not in self.wall_cells:
                    continue
                # Cell AABB in world space
                cx, cy = cell_to_world(col, row)
                h = CELL / 2.0
                x1, x2 = cx - h, cx + h
                y1, y2 = cy - h, cy + h
                # Nearest point on cell to ball centre
                nx = max(x1, min(px, x2))
                ny = max(y1, min(py, y2))
                dx, dy = px - nx, py - ny
                d = math.hypot(dx, dy)
                if 0 < d < r:
                    px += dx / d * (r - d)
                    py += dy / d * (r - d)
                elif d == 0:
                    # Ball centre exactly on wall edge — push right
                    px += r
        return px, py

    # ════════════════════════════════════════════════════
    # MAIN LOOP
    # ════════════════════════════════════════════════════
    def _tick(self, task):
        dt = min(globalClock.getDt(), 0.05)

        # Animate goal
        self._gt += dt
        self.goal_np.setZ(0.25 * abs(math.sin(self._gt * 2.2)))
        self.goal_np.setH(self.goal_np.getH() + 80 * dt)

        self._follow_cam()

        if not self.running:
            return task.cont

        # Turn
        if self.keys["arrow_left"]:  self.heading += TURN_SPEED * dt
        if self.keys["arrow_right"]: self.heading -= TURN_SPEED * dt

        # Move
        fwd = 0
        if self.keys["arrow_up"]:   fwd =  1
        if self.keys["arrow_down"]: fwd = -1

        rad = math.radians(self.heading)
        dx  = math.sin(rad) * fwd * MOVE_SPEED * dt
        dy  = math.cos(rad) * fwd * MOVE_SPEED * dt

        bp = self.ball.getPos()
        nx, ny = self._collide(bp.x + dx, bp.y + dy)
        self.ball.setPos(nx, ny, BALL_R)

        if fwd:
            self.ball.setR(self.ball.getR() - fwd * 5)

        # Win check — distance to goal
        gx, gy = self.goal_world
        if math.hypot(nx - gx, ny - gy) < CELL * 0.7:
            self._win()

        return task.cont


if __name__ == "__main__":
    BallMaze().run()

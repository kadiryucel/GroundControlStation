# model_loader.py
from PyQt5.QtOpenGL import QGLWidget
from PyQt5 import QtWidgets
from OpenGL.GL import *
from OpenGL.GLU import *
# obj_parser.py dosyasındaki fonksiyonun ismini güncelledik
import numpy as np

class ModelViewer(QGLWidget):
    def __init__(self, obj_path):
        super().__init__()
        self.obj_path = obj_path
        self.vbo_vertices = None
        self.vbo_texcoords = None
        self.vbo_normals = None
        self.vertices = None
        self.texcoords = None
        self.normals = None

        # BNO055 verileri
        self.orientationX = 0.0  # roll
        self.orientationY = 0.0  # pitch
        self.orientationZ = 0.0  # yaw
        self.Ax = 0.0
        self.Ay = 0.0
        self.Az = 0.0
        self.Gx = 0.0
        self.Gy = 0.0
        self.Gz = 0.0
        self.Mx = 0.0
        self.My = 0.0
        self.Mz = 0.0

        # Timer
        from PyQt5.QtCore import QTimer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def normalize_angle(self, angle):
        """Açıyı -180..180 aralığına getir"""
        return (angle + 180) % 360 - 180

    def initializeGL(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glClearColor(0.2, 0.2, 0.3, 1.0)

        # OBJ yükleme
        self.vertices, self.texcoords, self.normals = self.load_obj_data(self.obj_path)

        # Vertex VBO
        self.vbo_vertices = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_vertices)
        glBufferData(GL_ARRAY_BUFFER, self.vertices.nbytes, self.vertices, GL_STATIC_DRAW)

        # Texture coord VBO
        if self.texcoords.size > 0:
            self.vbo_texcoords = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_texcoords)
            glBufferData(GL_ARRAY_BUFFER, self.texcoords.nbytes, self.texcoords, GL_STATIC_DRAW)
            glEnable(GL_TEXTURE_2D)

        # Normal VBO
        if self.normals.size > 0:
            self.vbo_normals = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_normals)
            glBufferData(GL_ARRAY_BUFFER, self.normals.nbytes, self.normals, GL_STATIC_DRAW)

        # Işıklandırma
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [10.0, 10.0, 10.0, 1.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.2, 0.2, 0.2, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.8, 0.8, 0.8, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, w/h if h else 1, 0.1, 100)
        glMatrixMode(GL_MODELVIEW)
    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        gluLookAt(0, 1, 4, 0, 0, 0, 0, 1, 0)
        glPushMatrix()

        glScalef(0.25, 0.25, 0.25)

        roll = self.normalize_angle(self.orientationX)
        pitch = self.normalize_angle(self.orientationY)
        yaw = self.normalize_angle(self.orientationZ)

        glRotatef(yaw, 0, 0, 1)
        glRotatef(pitch, 0, 1, 0)
        glRotatef(roll, 1, 0, 0)

        # Malzeme rengi (RGB)
        glColor3f(0.8, 0.2, 0.2)  # istediğin renk

        # Vertex array
        glEnableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_vertices)
        glVertexPointer(3, GL_FLOAT, 0, None)

        # Normal array
        if self.normals.size > 0:
            glEnableClientState(GL_NORMAL_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_normals)
            glNormalPointer(GL_FLOAT, 0, None)

        glDrawArrays(GL_TRIANGLES, 0, len(self.vertices)//3)

        glDisableClientState(GL_VERTEX_ARRAY)
        if self.normals.size > 0:
            glDisableClientState(GL_NORMAL_ARRAY)

        glPopMatrix()


    def load_obj_data(self, filename):
        temp_vertices, temp_normals, temp_texcoords = [], [], []
        vertices, normals, texcoords = [], [], []
        with open(filename, "r") as file:
            for line in file:
                if line.startswith("v "):
                    parts = line.strip().split()
                    temp_vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith("vn "):
                    parts = line.strip().split()
                    temp_normals.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith("vt "):
                    parts = line.strip().split()
                    temp_texcoords.append([float(parts[1]), float(parts[2])])
                elif line.startswith("f "):
                    parts = line.strip().split()
                    for i in range(1, len(parts)-1):
                        idx_list = [parts[1], parts[i], parts[i+1]]
                        for idx in idx_list:
                            vals = idx.split("/")
                            v_idx = int(vals[0]) - 1
                            vertices.extend(temp_vertices[v_idx])
                            if len(vals) > 1 and vals[1]:
                                t_idx = int(vals[1]) - 1
                                texcoords.extend(temp_texcoords[t_idx])
                            if len(vals) > 2 and vals[2]:
                                n_idx = int(vals[2]) - 1
                                normals.extend(temp_normals[n_idx])

        vertex_array = np.array(vertices, dtype=np.float32).reshape(-1,3)
        # Pivot'u ortala
        center = np.mean(vertex_array, axis=0)
        centered_vertices = (vertex_array - center).flatten()
        return np.array(centered_vertices, dtype=np.float32), np.array(texcoords, dtype=np.float32), np.array(normals, dtype=np.float32)


"""Dependency-free dimensioned geometry shared by Blender and OBJ creation.

2026 C-UASC rules: approx. 5 m 'diameter'; no exact side or line thickness.
The assumed 5 m diagonal and 0.10 m stroke width are NOT official.
"""
import math


def board_side(span_m=5.0, size_mode='diagonal'):
    if span_m <= 0:
        raise ValueError('span_m must be positive')
    if size_mode not in ('diagonal', 'side'):
        raise ValueError('size_mode must be diagonal or side')
    return span_m / math.sqrt(2) if size_mode == 'diagonal' else span_m


def clip_poly(poly, axis, value, keep_greater):
    """Clip convex polygon to an x or y half-plane."""
    result = []
    def coord(point): return point[axis]
    def inside(point):
        return coord(point) >= value - 1e-10 if keep_greater else coord(point) <= value + 1e-10
    for i, end in enumerate(poly):
        start = poly[i-1]
        a, b = inside(start), inside(end)
        if a != b:
            difference = coord(end)-coord(start)
            t = (value-coord(start))/difference
            result.append((start[0] + t*(end[0]-start[0]), start[1] + t*(end[1]-start[1])))
        if b:
            result.append(end)
    return result


def shapes(span_m=5.0, size_mode='diagonal', stroke_width_m=0.10):
    side = board_side(span_m, size_mode)
    if not 0 < stroke_width_m < side * 0.3:
        raise ValueError('stroke_width_m must be positive and less than 30% of side')
    h = side / 2
    square = [(-h,-h), (h,-h), (h,h), (-h,h)]
    strokes = []
    for theta in (math.pi/4, -math.pi/4):
        ux, uy = math.cos(theta), math.sin(theta)
        nx, ny = -uy, ux
        half_length = side * 1.2
        half_width = stroke_width_m / 2
        poly = [
            (-ux*half_length-nx*half_width, -uy*half_length-ny*half_width),
            ( ux*half_length-nx*half_width,  uy*half_length-ny*half_width),
            ( ux*half_length+nx*half_width,  uy*half_length+ny*half_width),
            (-ux*half_length+nx*half_width, -uy*half_length+ny*half_width),
        ]
        for axis, value, greater in ((0,-h,True),(0,h,False),(1,-h,True),(1,h,False)):
            poly = clip_poly(poly, axis, value, greater)
        strokes.append(poly)
    return {'side_m':side, 'square':square, 'strokes':strokes}


def prism(poly, bottom, top):
    n=len(poly)
    vertices=[(x,y,bottom) for x,y in poly]+[(x,y,top) for x,y in poly]
    faces=[list(range(n-1,-1,-1)), list(range(n,2*n))]
    for i in range(n):
        j=(i+1)%n
        faces.append([i,j,j+n,i+n])
    return vertices,faces

"""Keep a selected return branch inside its configured corridor."""
import math


def distance_to_route(x, y, route):
    distances = []
    for a, b in zip(route, route[1:]):
        dx, dy = b['x']-a['x'], b['y']-a['y']
        length = dx*dx+dy*dy
        t = max(0., min(1., ((x-a['x'])*dx+(y-a['y'])*dy)/length)) if length else 0.
        distances.append(math.hypot(x-a['x']-t*dx, y-a['y']-t*dy))
    return min(distances, default=float('inf'))


def path_inside_route(points, route, width=1.2):
    return bool(points) and all(distance_to_route(x,y,route) <= width for x,y in points)

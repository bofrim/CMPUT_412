#!/usr/bin/env python
import rospy
import math
from sensor_msgs.msg import LaserScan
from demo3.msg import ZoneScan
from Utils import closest_object_in_range, DISTANCE_LIMIT
from Constants import (
    DISTANCE_LIMIT,
    OUTER_DISTANCE_LIMIT,
    NORMAL_DISTANCE_LIMIT,
    INNER_DISTANCE_LIMIT,
    RIGHT,
    OUTER_RIGHT,
    INNER_RIGHT,
    LEFT,
    OUTER_LEFT,
    INNER_LEFT,
)

ZONE_NUM = 6


def is_right_clear(zones):
    return (
        zones[OUTER_RIGHT] >= OUTER_DISTANCE_LIMIT
        and zones[RIGHT] >= NORMAL_DISTANCE_LIMIT
        and zones[INNER_RIGHT] >= INNER_DISTANCE_LIMIT
    )


def is_left_clear(zones):
    return (
        zones[OUTER_LEFT] >= OUTER_DISTANCE_LIMIT
        and zones[LEFT] >= NORMAL_DISTANCE_LIMIT
        and zones[INNER_LEFT] >= INNER_DISTANCE_LIMIT
    )


def is_straight_ahead_blocked(zones):
    return (
        zones[INNER_LEFT] < INNER_DISTANCE_LIMIT
        and zones[INNER_RIGHT] < INNER_DISTANCE_LIMIT
    )


def is_straight_ahead_clear(zones):
    return (
        zones[INNER_LEFT] >= INNER_DISTANCE_LIMIT
        and zones[LEFT] >= NORMAL_DISTANCE_LIMIT
        and zones[INNER_RIGHT] >= INNER_DISTANCE_LIMIT
        and zones[RIGHT] >= NORMAL_DISTANCE_LIMIT
    )


def is_straight_ahead_clear_nimble(zones):
    return (
        zones[INNER_LEFT] >= INNER_DISTANCE_LIMIT
        and zones[INNER_RIGHT] >= INNER_DISTANCE_LIMIT
    )


class zone_detector:
    def __init__(self):
        self.laser_scan_sub = rospy.Subscriber(
            "/scan", LaserScan, self.laser_scan_callback
        )
        self.zone_pub = rospy.Publisher("/zone_scan", ZoneScan, queue_size=1)
        self.scan_min_angle = None
        self.scan_max_angle = None
        self.scan_angle_increment = None

        self.object_distance = DISTANCE_LIMIT
        self.object_angle = 0.0

    def laser_scan_callback(self, msg):
        if (
            self.scan_min_angle is None
            or self.scan_max_angle is None
            or self.scan_angle_increment is None
        ):
            self.scan_min_angle = math.degrees(msg.angle_min)
            self.scan_max_angle = math.degrees(msg.angle_max)
            self.scan_angle_increment = math.degrees(msg.angle_increment)

        zone_span = (self.scan_max_angle - self.scan_min_angle) / ZONE_NUM
        zone_distances = []

        for x in range(0, ZONE_NUM):
            left_zone_bound = self.scan_min_angle + (zone_span * x)
            right_zone_bound = left_zone_bound + zone_span - self.scan_angle_increment
            _, distance = closest_object_in_range(
                msg.ranges,
                left_zone_bound,
                right_zone_bound,
                self.scan_min_angle,
                self.scan_angle_increment,
            )
            zone_distances.append(distance)

        print("DISTANCES: " + str(zone_distances))

        zone_msg = ZoneScan()
        zone_msg.distances = zone_distances
        self.zone_pub.publish(zone_msg)


if __name__ == "__main__":
    rospy.init_node("zone_detector")
    detector_node = zone_detector()
    rospy.spin()

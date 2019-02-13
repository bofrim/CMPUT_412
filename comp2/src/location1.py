#!/usr/bin/env python
import rospy, cv2, cv_bridge, numpy
import smach, smach_ros

from geometry_msgs.msg import Twist

class TurnLeft1(smach.State):
    def __init__(self, rate, pub_node):
        smach.State.__init__(self, outcomes=["detect1", "exit"])
        self.rate = rate
        self.vel_pub = pub_node

    def execute(self, userdata):
        return "detect1"


class Detect1(smach.State):
    def __init__(self, rate):
        smach.State.__init__(self, outcomes=["turn_right", "exit"])
        self.rate = rate

    def execute(self, userdata):
        return "turn_right"
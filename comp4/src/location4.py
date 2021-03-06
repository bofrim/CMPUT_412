#!/usr/bin/env python
import actionlib
import rospy, cv2, cv_bridge, numpy
import smach, smach_ros
import tf

from utility_states import NavState, DriveState

from comp2.msg import Centroid
from general_states import Drive

from actionlib_msgs.msg import GoalStatus
from ar_track_alvar_msgs.msg import AlvarMarker, AlvarMarkers
from geometry_msgs.msg import (
    Twist,
    Point,
    Quaternion,
    PoseWithCovarianceStamped,
    PoseWithCovariance,
    Pose,
)

from nav_msgs.msg import Odometry

from image_processing import study_shapes, get_red_mask, get_red_mask_image_det

from sensor_msgs.msg import Joy
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from kobuki_msgs.msg import Led, Sound
from utils import display_count, broadcast_box_sides, wait_for_odom_angle, extract_angle, standardize_theta, simple_turn
from config_globals import *

from location2 import get_the_shape


class DriverRamp(Drive):
    def __init__(self, rate, pub_node):
        super(DriverRamp, self).__init__(rate, pub_node, ["start", "exit"])

    def execute(self, userdata):
        self.path_centroid = Centroid()

        self.stop_distance = -1
        white_line_sub = rospy.Subscriber(
            "white_line_ramp_centroid", Centroid, self.image_callback
        )
        pose_pub = rospy.Publisher(
            "initialpose", PoseWithCovarianceStamped, queue_size=1
        )

        while not rospy.is_shutdown():
            if self.path_centroid.cx == -1 or self.path_centroid.cy == -1:
                rospy.loginfo("Sending initial pose...")
                initial_pose_cov_stamp = PoseWithCovarianceStamped()
                initial_pose_cov = PoseWithCovariance()
                initial_pose = Pose()
                initial_pose = WAYPOINT_MAP["off_ramp"]
                initial_pose_cov.pose = initial_pose
                initial_pose_cov_stamp.pose = initial_pose_cov

                for _ in range(0, 3):
                    pose_pub.publish(initial_pose_cov_stamp)
                    rospy.loginfo(" ...Sent.")
                    rospy.sleep(0.3)

                pose_pub.unregister()
                white_line_sub.unregister()
                return "start"

            self.vel_pub.publish(self.twist)
            self.rate.sleep()

        for _ in range(0, 4):
            twist = Twist()
            twist.linear.x = 0.5
            self.pub_node.publish(twist)

            rospy.sleep(0.2)

        pose_pub.unregister()
        white_line_sub.unregister()

        return "exit"
    

class BoxSurvey(smach.State):
    def __init__(self, rate, pub_node, led_nodes, sound_node):
        smach.State.__init__(self, outcomes=["tag_scan_1", "exit"])
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()
        self.pub_node = pub_node
        self.led_nodes = led_nodes
        self.sound_node = sound_node
        self.rate = rate
        self.ar_focus_id = -1
        self.target_repetitions = 0
        self.listen = tf.TransformListener()
        self.br = tf.TransformBroadcaster()

    def execute(self, user_data):
        self.reset_vars()

        self.ar_sub = rospy.Subscriber(
            MARKER_POSE_TOPIC, AlvarMarkers, self.ar_callback, queue_size=1
        )
        self.drive_to_vantage_point()
        self.record_box()
        self.ar_sub.unregister()
        return "tag_scan_1"

    def reset_vars(self):
        global g4_box_left_side
        global g4_box_right_side
        global g4_box_id
        global g4_target_location
        
        self.ar_focus_id = -1
        self.target_repetitions = 0
        g4_box_id = -1
        g4_box_left_side = None
        g4_box_right_side = None
        g4_target_location = Pose()

    def drive_to_vantage_point(self):
        goal_pose = MoveBaseGoal()
        goal_pose.target_pose.header.frame_id = "map"
        goal_pose.target_pose.pose = WAYPOINT_MAP["box_vantage"]
        self.client.send_goal(goal_pose)
        self.client.wait_for_result()

    def record_box(self):
        global g4_box_left_side
        global g4_box_right_side

        while (
            self.ar_focus_id == -1 or self.target_repetitions < 4
        ) and not rospy.is_shutdown():
            twist = Twist()
            twist.angular.x = 0.2
            self.pub_node.publish(twist)
            self.rate.sleep()

        display_count(2, self.led_nodes, color_primary=Led.RED)
        sound_msg = Sound()
        sound_msg.value = Sound.ON
        self.sound_node.publish(sound_msg)

        rospy.sleep(2)
        g4_box_left_side = self.listen.lookupTransform(
            "/map", "box_left", rospy.Time(0)
        )
        g4_box_right_side = self.listen.lookupTransform(
            "/map", "box_right", rospy.Time(0)
        )

    def ar_callback(self, msg):
        global g4_box_id
        global g4_box_left_side
        global g4_box_right_side

        if not msg.markers:
            self.ar_focus_id = -1
            self.target_repetitions = 0
            return

        for marker in msg.markers:
            if marker.id == self.ar_focus_id:
                self.target_repetitions = self.target_repetitions + 1
                broadcast_box_sides(self.br, self.listen, "ar_marker_" + str(marker.id))
                g4_box_id = self.ar_focus_id

            else:
                self.ar_focus_id = marker.id
                self.target_repetitions = 0

            break


class TagScan1(smach.State):
    def __init__(self, rate, pub_node, led_nodes, sound_node):
        smach.State.__init__(
            self,
            outcomes=["tag_scan_2", "found_tag", "exit"],
            output_keys=["push_start_tf"],
        )
        self.rate = rate
        self.pub_node = pub_node
        self.led_nodes = led_nodes
        self.sound_node = sound_node
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()
        self.ar_focus_id = -1
        self.target_repetitions = 0
        self.found_target = False
        self.listen = tf.TransformListener()

    def execute(self, user_data):
        self.reset_vars()

        self.ar_sub = rospy.Subscriber(
            MARKER_POSE_TOPIC, AlvarMarkers, self.ar_callback, queue_size=1
        )

        self.drive_to_scan_point()
        self.scan()

        if self.because_i_still_havent_found_what_im_looking_for():
            self.ar_sub.unregister()
            return "tag_scan_2"
        else:
            user_data.push_start_tf = "box_left"

            self.indicate_tag_found()
            self.drive_to_neutral_point()
            self.ar_sub.unregister()
            return "found_tag"

    def reset_vars(self):
        self.ar_focus_id = -1
        self.target_repetitions = 0
        self.found_target = False


    def drive_to_scan_point(self):
        goal_pose = MoveBaseGoal()
        goal_pose.target_pose.header.frame_id = "map"
        goal_pose.target_pose.pose = WAYPOINT_MAP["scan_east"]
        self.client.send_goal(goal_pose)
        self.client.wait_for_result()

    def drive_to_neutral_point(self):
        goal_pose = MoveBaseGoal()
        goal_pose.target_pose.header.frame_id = "map"
        goal_pose.target_pose.pose = WAYPOINT_MAP["scan_west"]
        self.client.send_goal(goal_pose)
        self.client.wait_for_result()

    def scan(self):
        global g4_target_location
        start_angle = wait_for_odom_angle()
        while (
            self.ar_focus_id not in set([1, 2, 3, 4, 5]) or self.target_repetitions < 3
        ) and not rospy.is_shutdown():
            if abs(wait_for_odom_angle() - start_angle) > 104:
                return
            twist = Twist()
            twist.angular.z = 0.3
            self.pub_node.publish(twist)
            self.rate.sleep()

        print("FOUND MARKER ID: ", self.ar_focus_id)
        ar_trans, ar_rot = self.listen.lookupTransform(
            "odom", "ar_marker_" + str(self.ar_focus_id), rospy.Time(0)
        )
        g4_target_location.position = Point(*ar_trans)
        g4_target_location.orientation = Quaternion(*ar_rot)

        print "TARGET POSITION: " + str(g4_target_location.position)
        self.found_target = True

    def indicate_tag_found(self):
        display_count(2, self.led_nodes)
        sound_msg = Sound()
        sound_msg.value = Sound.ON
        self.sound_node.publish(sound_msg)

    def because_i_still_havent_found_what_im_looking_for(self):
        return not self.found_target

    def ar_callback(self, msg):
        if not msg.markers:
            self.target_repetitions = 0
            return

        for marker in msg.markers:
            if marker.id != g4_box_id:
                if marker.id == self.ar_focus_id:
                    self.target_repetitions = self.target_repetitions + 1
                else:
                    self.ar_focus_id = marker.id
                    self.target_repetitions = 0
                break


class TagScan2(smach.State):
    def __init__(self, rate, pub_node, led_nodes, sound_node):
        smach.State.__init__(
            self,
            outcomes=["tag_scan_1", "found_tag", "exit"],
            output_keys=["push_start_tf"],
        )
        self.rate = rate
        self.pub_node = pub_node
        self.led_nodes = led_nodes
        self.sound_node = sound_node
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()
        self.ar_focus_id = -1
        self.target_repetitions = 0
        self.found_target = False
        self.listen = tf.TransformListener()

    def execute(self, user_data):
        self.reset_vars()

        self.ar_sub = rospy.Subscriber(
            MARKER_POSE_TOPIC, AlvarMarkers, self.ar_callback, queue_size=1
        )

        self.drive_to_scan_point()
        self.scan()
        user_data.push_start_tf = "box_right"
        self.indicate_tag_found()

        self.ar_sub.unregister()
        return "found_tag"

    def reset_vars(self):
        self.ar_focus_id = -1
        self.target_repetitions = 0
        self.found_target = False

    def drive_to_scan_point(self):
        goal_pose = MoveBaseGoal()
        goal_pose.target_pose.header.frame_id = "map"
        goal_pose.target_pose.pose = WAYPOINT_MAP["scan_west"]
        self.client.send_goal(goal_pose)
        self.client.wait_for_result()

    def scan(self, max_error=3):
        global g4_target_location
        target_theta = standardize_theta(wait_for_odom_angle()-150)
        while (
            self.ar_focus_id not in set([1, 2, 3, 4, 5]) or self.target_repetitions < 3
        ) and not rospy.is_shutdown():
            if abs(target_theta - wait_for_odom_angle()) < max_error:
                print "NOT FOUND - ASSUMING WAYPOINT 3"
                g4_target_location = WAYPOINT_MAP["3"]
                self.found_target = True
                return
            twist = Twist()
            twist.angular.z = -0.3
            self.pub_node.publish(twist)
            self.rate.sleep()

        print("FOUND MARKER ID: ", self.ar_focus_id)
        ar_trans, ar_rot = self.listen.lookupTransform(
            "odom", "ar_marker_" + str(self.ar_focus_id), rospy.Time(0)
        )
        g4_target_location.position = Point(*ar_trans)
        g4_target_location.orientation = Quaternion(*ar_rot)
        self.found_target = True

    def because_i_still_havent_found_what_im_looking_for(self):
        return not self.found_target

    def indicate_tag_found(self):
        display_count(2, self.led_nodes)
        sound_msg = Sound()
        sound_msg.value = Sound.ON
        self.sound_node.publish(sound_msg)

    def ar_callback(self, msg):
        if not msg.markers:
            self.target_repetitions = 0
            return

        for marker in msg.markers:
            if marker.id != g4_box_id:
                if marker.id == self.ar_focus_id:
                    self.target_repetitions = self.target_repetitions + 1
                else:
                    self.ar_focus_id = marker.id
                    self.target_repetitions = 0
                break


class Push(smach.State):
    def __init__(self, rate, pub_node, led_nodes, sound_node):
        smach.State.__init__(
            self,
            outcomes=["on_ramp", "exit"],
            input_keys=["push_start_tf"],
        )
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()
        self.rate = rate
        self.pub_node = pub_node
        self.led_nodes = led_nodes
        self.sound_node = sound_node
        self.curr_error = 0
        self.kp = -0.01
        self.distance_to_target = 1000
        self.reference = 0
        self.listen = tf.TransformListener()
        self.br = tf.TransformBroadcaster()

    def execute(self, user_data):
        self.reset_vars()

        self.ar_sub = rospy.Subscriber(
            MARKER_POSE_TOPIC, AlvarMarkers, self.ar_callback, queue_size=1
        )
        odom_sub = rospy.Subscriber("odom", Odometry, self.odom_callback)
        rospy.wait_for_message("odom", Odometry)
        if self.drive_to_push_point(user_data.push_start_tf):
            self.reference = wait_for_odom_angle()
            self.push_to_goal()
            self.drive_backwards()
            
        self.ar_sub.unregister()
        odom_sub.unregister()
        return "on_ramp"

    def reset_vars(self):
        self.curr_error = 0
        self.kp = -0.01
        self.distance_to_target = 1000
        self.reference = 0

    def drive_to_push_point(self, target_frame_id):
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = target_frame_id
        goal.target_pose.pose.position = Point(0, 0, 0)
        goal.target_pose.pose.orientation = Quaternion(0, 0, 0, 1)
        self.client.send_goal(goal)
        result = self.client.wait_for_result()

        display_count(2, self.led_nodes, Led.GREEN, Led.RED)

        print "REACH GOAL RESULT: " + str(result)
        return result

    def push_to_goal(self):
        #TODO: Possibly add in case where distance is increasing (driving the wrong way)
        while self.distance_to_target > 0.45:
            twist = Twist()
            twist.linear.x = SPEED * 0.8
            twist.angular.z = self.kp * self.curr_error

            self.pub_node.publish(twist)
            self.rate.sleep()

    def drive_backwards(self):
        twist = Twist()
        twist.linear.x = -0.3
        for _ in range(12):
            self.pub_node.publish(twist)
            self.rate.sleep()

    def odom_callback(self, msg):
        robot_pose = msg.pose.pose
        theta = extract_angle(msg.pose.pose)
        self.distance_to_target = abs(
            g4_target_location.position.y - robot_pose.position.y
        )
        print "DISTANCE: " + str(self.distance_to_target)
        self.curr_error = theta - self.reference

    def ar_callback(self, msg):
        global g4_box_id
        if not msg.markers:
            self.ar_focus_id = -1
            self.target_repetitions = 0
            return

        for marker in msg.markers:
            if marker.id == g4_box_id:
                broadcast_box_sides(self.br, self.listen, "ar_marker_" + str(marker.id))


class ShapeScan(smach.State):
    def __init__(self, rate, pub_node, led_nodes, sound_node):
        smach.State.__init__(self, outcomes=["done", "exit"])
        self.rate = rate
        self.pub_node = pub_node
        self.led_nodes = led_nodes
        self.sound_node = sound_node
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()

    def execute(self, userdata):
        for spot_num in range(8, 5, -1):
            parking_spot = MoveBaseGoal()
            parking_spot.target_pose.header.frame_id = "map"
            parking_spot.target_pose.pose = WAYPOINT_MAP[str(spot_num)]

            self.client.send_goal(parking_spot)
            self.client.wait_for_result()

            msg = Twist()
            msg.linear.x = -0.2

            for _ in range(0, 3):
                self.pub_node.publish(msg)
                rospy.sleep(0.2)

            shape = study_shapes(get_red_mask_image_det, max_samples=60, confidence=0.5)

            #if shape == Shapes.square:
            if shape == get_the_shape():
                display_count(2, self.led_nodes, color_primary=Led.ORANGE)
                sound_msg = Sound()
                sound_msg.value = Sound.ON
                self.sound_node.publish(sound_msg)

                msg.linear.x = 0.2
                for _ in range(0, 3):
                    self.pub_node.publish(msg)
                    rospy.sleep(0.2)

                display_count(
                    3,
                    self.led_nodes,
                    color_primary=Led.ORANGE,
                    color_secondary=Led.GREEN,
                )
                break

        return "done"


class OnRamp(smach.State):
    def __init__(self, rate):
        smach.State.__init__(self, outcomes=["drive"])
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.client.wait_for_server()
        self.rate = rate

    def execute(self, userdata):
        pose_prepare = MoveBaseGoal()
        pose_prepare.target_pose.header.frame_id = "map"
        pose_prepare.target_pose.pose = WAYPOINT_MAP["scan_westest"]

        self.client.send_goal(pose_prepare)
        self.client.wait_for_result()

        pose_ramp = MoveBaseGoal()
        pose_ramp.target_pose.header.frame_id = "map"
        pose_ramp.target_pose.pose = WAYPOINT_MAP["on_ramp"]

        self.client.send_goal(pose_ramp)
        self.client.wait_for_result()

        return "drive"


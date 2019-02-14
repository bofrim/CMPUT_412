#!/usr/bin/env python

import rospy, cv2, cv_bridge, numpy
import smach, smach_ros

from comp2.msg import Centroid
from sensor_msgs.msg import Image


class WhiteLineTracker:
    def __init__(self):
        self.bridge = cv_bridge.CvBridge()
        self.image_sub = rospy.Subscriber(
            "camera/rgb/image_raw", Image, self.image_callback
        )
        self.centroid_pub = rospy.Publisher(
            "white_line_centroid", Centroid, queue_size="1"
        )

    def image_callback(self, msg):
        # mask = get_white_mask(msg)
        # curr_err = path_mass_center(mask)

        image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        lower_white = numpy.array([0, 0, 190])
        upper_white = numpy.array([360, 10, 255])
        mask = cv2.inRange(hsv, lower_white, upper_white)

        h, w, d = image.shape
        search_top = h * 0.80
        search_bot = search_top + 60
        mask[0:search_top, 0:w] = 0
        mask[search_bot:h, 0:w] = 0
        M = cv2.moments(mask)
        if M["m00"] > 1000:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            cv2.circle(image, (cx, cy), 20, (0, 0, 255), -1)

            centroid_msg = Centroid()
            centroid_msg.cx = cx
            centroid_msg.cy = cy
            centroid_msg.err = cx - w / 2

            self.centroid_pub.publish(centroid_msg)
        else:
            centroid_msg = Centroid()
            centroid_msg.cx = -1
            centroid_msg.cy = -1
            centroid_msg.err = 0
            self.centroid_pub.publish(centroid_msg)

        cv2.imshow("window", mask)
        cv2.waitKey(3)


rospy.init_node("white_line_finder")
follower = WhiteLineTracker()
rospy.spin()


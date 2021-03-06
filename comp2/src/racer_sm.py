#!/usr/bin/env python
import general_states
import rospy
import smach
import smach_ros

from location1 import TurnLeft1, Detect1
from location2 import (
    TurnLeft2Start,
    DriveToObjects,
    DriveFromObjects,
    Detect2,
    Turn180,
    TurnLeft2End,
)
from location3 import AdjustmentTurn3, TurnLeft3, Detect3, TurnRight3

from general_states import Driver, Advancer, AtLine, TurnRight
from geometry_msgs.msg import Twist
from kobuki_msgs.msg import Led, Sound
from time import time


def main():
    rospy.init_node("robber_state_machine")

    state_machine = smach.StateMachine(outcomes=["complete", "exit"])
    state_introspection_server = smach_ros.IntrospectionServer(
        "server_name", state_machine, "/SM_ROOT"
    )
    state_introspection_server.start()

    cmd_vel_pub = rospy.Publisher("cmd_vel", Twist, queue_size=1)

    light_pubs = []
    light_pubs.append(rospy.Publisher("/mobile_base/commands/led1", Led, queue_size=1))
    light_pubs.append(rospy.Publisher("/mobile_base/commands/led2", Led, queue_size=1))
    sound_pub = rospy.Publisher("/mobile_base/commands/sound", Sound, queue_size=1)
    led_off_msg = Led()
    led_off_msg.value = Led.BLACK
    light_pubs[0].publish(led_off_msg)
    light_pubs[1].publish(led_off_msg)
    rate = rospy.Rate(10)

    with state_machine:
        smach.StateMachine.add(
            "DRIVE",
            Driver(rate, cmd_vel_pub),
            transitions={"advance": "ADVANCE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "ADVANCE",
            Advancer(rate, cmd_vel_pub),
            transitions={"at_line": "AT_LINE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "AT_LINE",
            AtLine(rate, light_pubs),
            transitions={
                "drive": "DRIVE",
                "turn_left_1": "TURN_LEFT_1",
                "turn_left_2_start": "TURN_LEFT_2_START",
                "turn_left_2_end": "TURN_LEFT_2_END",
                "adjust_3": "ADJUST_3",
                "turn_left_3": "TURN_LEFT_3",
                "exit": "exit",
            },
        )

        smach.StateMachine.add(
            "TURN_LEFT_1",
            TurnLeft1(rate, cmd_vel_pub),
            transitions={"detect1": "DETECT1", "exit": "exit"},
        )

        smach.StateMachine.add(
            "DETECT1",
            Detect1(rate, light_pubs, sound_pub),
            transitions={"turn_right": "TURN_RIGHT", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_RIGHT",
            TurnRight(rate, cmd_vel_pub),
            transitions={"drive": "DRIVE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_LEFT_2_START",
            TurnLeft2Start(rate, cmd_vel_pub),
            transitions={"drive_to_objects": "DRIVE_TO_OBJECTS", "exit": "exit"},
        )

        smach.StateMachine.add(
            "DRIVE_TO_OBJECTS",
            DriveToObjects(rate, cmd_vel_pub, light_pubs),
            transitions={"detect2": "DETECT2", "exit": "exit"},
        )

        smach.StateMachine.add(
            "DETECT2",
            Detect2(rate),
            transitions={"turn_180": "TURN_180", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_180",
            Turn180(rate, cmd_vel_pub),
            transitions={"drive_from_objects": "DRIVE_FROM_OBJECTS", "exit": "exit"},
        )

        smach.StateMachine.add(
            "DRIVE_FROM_OBJECTS",
            DriveFromObjects(rate, cmd_vel_pub),
            transitions={"advance": "ADVANCE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_LEFT_2_END",
            TurnLeft2End(rate, cmd_vel_pub),
            transitions={"drive": "DRIVE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "ADJUST_3",
            AdjustmentTurn3(rate, cmd_vel_pub),
            transitions={"drive": "DRIVE", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_LEFT_3",
            TurnLeft3(rate, cmd_vel_pub),
            transitions={"detect3": "DETECT3", "exit": "exit"},
        )

        smach.StateMachine.add(
            "DETECT3",
            Detect3(rate, light_pubs, sound_pub),
            transitions={"turn_right3": "TURN_RIGHT3", "exit": "exit"},
        )

        smach.StateMachine.add(
            "TURN_RIGHT3",
            TurnRight3(rate, cmd_vel_pub),
            transitions={"drive": "DRIVE", "exit": "exit"},
        )

    state_machine.execute()
    state_introspection_server.stop()


if __name__ == "__main__":
    main()

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="competition_vision",
            executable="vision_camera_node",
            output="screen",
        ),
        Node(
            package="competition_tracker",
            executable="tracker_node",
            output="screen",
        ),
        Node(
            package="competition_manager",
            executable="manager_node",
            output="screen",
        ),
        Node(
            package="competition_mavros_stub",
            executable="mavros_stub_node",
            output="screen",
        ),
    ])

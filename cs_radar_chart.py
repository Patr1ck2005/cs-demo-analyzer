import os
import time
from datetime import datetime

from manim import *
from manim.opengl import *
import pandas as pd

from utils.image_pre import crop_image_to_circle, manim_crop_image_to_circle, manim_apply_opacity_to_image

"""
manim -pqh --format=mov --transparent cs_radar_chart.py PlayerRadarChart
manim cs_radar_chart.py -p --renderer=opengl

manim -pql cs_radar_chart.py PlayerRadarChart

manim -pqh cs_radar_chart.py PlayerRadarChart
"""


class PlayerRadarChart(Scene):
    def __init__(self):
        super().__init__()

        # 设置背景颜色
        self.camera.background_color = DARKER_GRAY

        self.highlight_color = YELLOW
        self.normal_color = WHITE

        self.radar_size = 2.4

        # left
        self.ticks = None
        self.labels = None
        self.marks = None
        self.value_labels = None
        self.radar_chart = None
        self.chart_background_rect = None
        # right
        self.player_icon = None

        self.start_time = None

        # 定义每个属性的最小值和最大值
        self.attribute_ranges = {
            'KPR': (0.5, 0.9),
            'Survivals': (0.2, 0.4),
            'ADR': (50, 90),
            'Headshot%': (30, 50),
            'FirstKillsPerRound': (0, 0.2),
            'RWS': (6, 10),
            'Rating': (0.7, 1.3),
            'Rating Pro': (0.7, 1.2)
        }

        ###############################################################################################################
        # 选择要提取的选手数据
        self.attributes = ['KPR', 'Survivals', 'ADR', 'Headshot%', 'FirstKillsPerRound', 'Rating Pro']
        # # 定义每个选手入场时间的列表（单位为秒）
        # self.entry_times = [46, 55, 65, 75, 85, 93, 103, 113, 123, 133, 143]
        # ###############################################################################################################
        # self.time_control = {
        #     'show_title': 3,
        #     'show_ticks_def': 12,
        #     'show_ticks_max': 21,
        #     'show_ticks_min': 31,
        #     'end_intro': 44,
        #     'show': self.entry_times,
        #     'end_show': 153,
        # }
        # # 定义每个选手入场时间的列表（单位为秒）for
        # self.entry_times = [41, 50, 61, 71, 82, 95]
        # ###############################################################################################################
        # self.time_control = {
        #     'show_title': 3,
        #     'show_ticks_def': 13,
        #     'show_ticks_max': 21,
        #     'show_ticks_min': 28,
        #     'end_intro': 38,
        #     'show': self.entry_times,
        #     'end_show': 115,
        # }
        # 定义每个选手入场时间的列表（单位为秒）So beautiful
        self.entry_times = [31, 40, 48, 55, 63, 74]
        ###############################################################################################################
        self.time_control = {
            'show_title': 1,
            'show_ticks_def': 8,
            'show_ticks_max': 16,
            'show_ticks_min': 23,
            'end_intro': 29,
            'show': self.entry_times,
            'end_show': 83,
        }
        # self.title_text = "2024\n上海Major海选"
        self.title_text = "2024\n中秋假期"
        self.music = None

    def construct(self):
        # # 添加背景音乐
        if self.music:
            self.add_sound(self.music, gain=-10)  # -10降低音量
        # 读取 CSV 数据
        # dataset_name = 'major_data'
        dataset_name = 'festival_data'
        data = self.preprocess_player_data(f"radar_data/{dataset_name}/player_statistics.csv")

        self.start_time = self.renderer.time

        self._show_title()

        self._show_ticks()

        current_time = self.renderer.time - self.start_time
        self.wait(self.entry_times[0] - current_time)
        # 循环展示选手，控制精确的时间切换
        for i in range(len(self.entry_times)):
            print(f"下面开始展示选手{data.iloc[i]['ID']}")
            self._show_player_data(i, data.iloc[i], display_time=10)
            if i == len(self.entry_times) - 1:
                self.play(Uncreate(self.radar_chart),)
                self.play(AnimationGroup(
                    ShrinkToCenter(self.ticks),
                    ShrinkToCenter(self.chart_background_rect),
                    lag_ratio=0.2,
                ))
        self._show_end()

    def _show_title(self):
        current_time = self.renderer.time - self.start_time
        self.wait(self.time_control['show_title'] - current_time)

        # 创建主标题和副标题
        self.main_title = Text(self.title_text, font_size=80, color=WHITE)
        subtitle = Text("群友数据图", font_size=60, color=WHITE)

        # 设置标题和副标题的位置
        self.main_title.to_edge(UP, buff=1.5)
        subtitle.next_to(self.main_title, DOWN, buff=0.5)

        # 播放标题淡入效果
        self.play(Write(self.main_title, scale=1.5), run_time=3)
        self.wait(1.5)

        # 播放副标题淡入效果
        self.play(Write(subtitle, shift=DOWN), run_time=1.5)

        # 以下一次场景搭建的时刻来计算当前需要等待的世界
        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(self.time_control['show_ticks_def'] - current_time - out_time)
        print(self.start_time)
        print(current_time)
        print(self.time_control['show_ticks_def'] - current_time - out_time)

        # 将标题和副标题一起淡出
        self.play(FadeOut(self.main_title), FadeOut(subtitle))

    def _show_ticks(self):
        chart_background_rect = Rectangle(width=7, height=6, color=BLACK, fill_opacity=0.3)
        # 生成标度线
        ticks = self._draw_ticks()
        ticks.set_z_index(2)
        # 生成标签
        labels, _, _ = self._draw_labels()
        labels.set_z_index(2)

        # # 播放
        # 先创建动画, 不播放
        ticks_animation = AnimationGroup(
            *[Create(tick) for tick in ticks],  # 使用生成的对象创建动画
            lag_ratio=0.25  # 设置每个动画之间的����
        )
        # 设置雷达图标签动画
        label_animation = AnimationGroup(
            *[Write(label) for label in labels][::-1],  # 使用生成的对象创建动画
            lag_ratio=0.6  # 设置每个动画之间的延迟
        )
        chart_background_rect.set_z_index(0)

        # 播放数据维度
        title = Text("数据维度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        self.play(AnimationGroup(
            GrowFromCenter(chart_background_rect),
            Write(title),
            lag_ratio=0.2,
        ))
        self.play(AnimationGroup(
            ticks_animation,
            label_animation,
            lag_ratio=1
        ))

        # 以下一次场景搭建的时刻来计算当前需要等待的世界
        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(self.time_control['show_ticks_max'] - current_time - out_time)
        self.play(FadeOut(title))
        print(current_time)
        print(self.time_control['show_ticks_def'] - current_time - out_time)

        # 播放最大刻度
        title = Text("最大刻度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        bigger_background_rect = Rectangle(width=9, height=6, color=BLACK, fill_opacity=0.3)
        bigger_background_rect.set_z_index(0)
        self.play(Write(title))
        self.wait(0.5)
        _, value_labels, _ = self._draw_labels(max_ticks=True)
        value_animation = AnimationGroup(
            Transform(chart_background_rect, bigger_background_rect),
            *[Write(value_label) for value_label in value_labels][::-1],
            lag_ratio=0.1  # 设置每个动画之间的延迟
        )
        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            hexagon_vertices.append(self.polar_to_cartesian(i, max(self.attribute_ranges[attr]),
                                                            *self.attribute_ranges[attr]) * self.radar_size)
        biggest_radar_chart = Polygon(*hexagon_vertices).set_stroke(width=5, color=self.highlight_color).set_fill(
            self.highlight_color, opacity=0.2)
        biggest_radar_chart.set_z_index(3)
        self.play(GrowFromCenter(biggest_radar_chart))
        self.play(value_animation)

        # 以下一次场景搭建的时刻来计算当前需要等待的世界
        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(self.time_control['show_ticks_min'] - current_time - out_time)
        self.play(FadeOut(title), FadeOut(value_labels))

        # 播放最小刻度
        title = Text("最小刻度", font_size=40, color=WHITE).next_to(chart_background_rect, direction=UP)
        self.play(Write(title))
        self.wait(0.5)
        _, value_labels, _ = self._draw_labels(min_ticks=True)
        value_animation = AnimationGroup(
            *[Write(value_label) for value_label in value_labels][::-1],  # 使用生成的对象创建动画
            lag_ratio=0.1  # 设置每个动画之间的延迟
        )
        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            hexagon_vertices.append(
                self.polar_to_cartesian(i, (min(self.attribute_ranges[attr])
                                            + 0.05 * (self.attribute_ranges[attr][1] - self.attribute_ranges[attr][0])),
                                        *self.attribute_ranges[attr]) * self.radar_size)
        smallest_radar_chart = Polygon(*hexagon_vertices).set_stroke(width=5, color=RED).set_fill(RED, opacity=0.2)
        smallest_radar_chart.set_z_index(3)
        self.play(Transform(biggest_radar_chart, smallest_radar_chart))
        self.play(value_animation)

        # 以下一次场景搭建的时刻来计算当前需要等待的世界
        current_time = self.renderer.time - self.start_time
        out_time = 1
        self.wait(self.time_control['end_intro'] - current_time - out_time)
        self.play(
            FadeOut(title),
            FadeOut(biggest_radar_chart),
            FadeOut(chart_background_rect),
            FadeOut(ticks),
            FadeOut(labels),
            FadeOut(value_labels),
        )

    def _show_end(self):
        # 创建��标题
        title = Text("Thinks for Watching", font_size=60, color=WHITE)
        # 记录生成日期
        subtitle = Text(datetime.now().strftime("%Y年%m月%d日"), font_size=50, color=WHITE)

        # 设置��标题的位置
        title.to_edge(UP, buff=1.5)
        subtitle.next_to(title, buff=2, direction=DOWN)

        # ���放��标题��入效果
        self.play(Write(title, shift=DOWN), run_time=2.5)
        self.play(Write(subtitle), run_time=1.5)
        self.wait(2.5)

        # ���放��标题��出效果
        self.play(FadeOut(title), FadeOut(subtitle))
        #
        # self.remove_sound(self.music)  # 停止音乐

    def _show_player_data(self, index, player_data, display_time):
        if self.chart_background_rect is None:
            self.chart_background_rect = Rectangle(width=7, height=7, color=BLACK, fill_opacity=0.5)
            self.chart_background_rect.to_edge(LEFT)
            self.chart_background_rect.set_z_index(0)

        # 绘制雷达图
        left_animation = self._draw_chart(player_data)

        # 显示选手头像
        icon_path_png = f"radar_data/{player_data['ID']}.png"
        icon_path_jpg = f"radar_data/{player_data['ID']}.jpg"
        # 首先尝试读取png文件
        if os.path.exists(icon_path_png):
            # 如果png文件存在，加载png文件
            player_icon = manim_crop_image_to_circle(icon_path_png).scale(2)
        elif os.path.exists(icon_path_jpg):
            # 如果jpg文件存在，加载jpg文件
            player_icon = manim_crop_image_to_circle(icon_path_jpg).scale(2)
        else:
            # 如果找不到头像文件，用圆形替代
            player_icon = manim_crop_image_to_circle(f"radar_data/default.jpg").scale(2)
        player_icon.to_edge(RIGHT, buff=1.8)

        # 创建一个圆形边框，略大于图片，表示边框
        circle_border = Circle(radius=player_icon.width / 2, color=LOGO_WHITE, stroke_width=8).move_to(player_icon.get_center())

        player_icon_animation_in = AnimationGroup(
            GrowFromEdge(player_icon, edge=RIGHT),
            Create(circle_border),
            lag_ratio=1.2
        )
        player_icon_animation_out = AnimationGroup(
            FadeOut(player_icon),
            FadeOut(circle_border)
        )

        # 绘制选手ID
        player_id_animation_in, player_id_animation_out = self.show_player_id(player_data, player_icon)

        # 显示队伍图标
        team_icon_path = f"radar_data/{player_data['team']}.png"
        if os.path.exists(team_icon_path):
            team_icon = manim_apply_opacity_to_image(team_icon_path, 0.5).scale_to_fit_height(3.2).scale(2)
        else:
            # 如果找不到队伍图标文件，用圆形替代
            team_icon = Circle(radius=2, color=GREEN).set_opacity(0)
        team_icon.move_to(player_icon)

        # 设置层级关系
        team_icon.set_z_index(1)
        player_icon.set_z_index(2)
        circle_border.set_z_index(3)

        team_animation_in = AnimationGroup(
            GrowFromCenter(team_icon)
        )
        team_animation_out = AnimationGroup(
            ShrinkToCenter(team_icon),
            FadeOut(team_icon)
        )

        # 播放进场动画
        id_and_icon_animation = AnimationGroup(
            player_id_animation_in,
            player_icon_animation_in,
            lag_ratio=0.3
        )
        team_animation = Succession(
            team_animation_in,
            team_icon.animate.scale(0.75),
        )
        if index == 0:  # 首次
            self.play(
                AnimationGroup(
                    id_and_icon_animation,
                    team_animation,
                    AnimationGroup(
                        GrowFromCenter(self.chart_background_rect),
                        left_animation,
                        lag_ratio=0.3),
                    lag_ratio=0.2))
        else:  # 常驻
            self.play(AnimationGroup(
                left_animation,
                id_and_icon_animation,
                team_animation,
                lag_ratio=0.1
            ))
        # 等待一段时间后，进行退场
        # self.wait(display_time)
        current_time = self.renderer.time - self.start_time
        out_time = 2
        if index < len(self.entry_times) - 1:
            self.wait(self.entry_times[index + 1] - current_time - out_time)
        else:
            self.wait(self.time_control['end_show'] - current_time - out_time)
        # 播放退场动画
        # 设置雷达图标签动画
        label_animation = AnimationGroup(
            *[FadeOut(mark) for mark in self.marks],
            *list(zip([FadeOut(label) for label in self.labels],
                      [FadeOut(value_label) for value_label in self.value_labels]))[::-1],  # 使用生成的对象创建动画
            lag_ratio=0.06  # 设置每个动画之间的延迟
        )
        self.play(AnimationGroup(label_animation,
                                 player_icon_animation_out,
                                 team_animation_out,
                                 player_id_animation_out), run_time=2)

    def polar_to_cartesian(self, index, value, min_value, max_value):
        # 角度计算：确保每个顶点按顺时针均匀分布, 从顶点开始计数
        angle = - (index % 6 - 1) * (TAU / 6) + PI / 6  # 6个顶点
        # 标准化数值，将其映射到 [0, 1] 范围内
        normalized_value = max((value - min_value), 0) / (max_value - min_value)
        radius = normalized_value  # 使用标准化后的值作为半径
        return radius * np.array([np.cos(angle), np.sin(angle), 0])

    def _draw_chart(self, player_data):
        # 生成标度线
        if self.ticks is None:
            ticks = self._draw_ticks()
            self.shift_vector = self.chart_background_rect.get_center() - ticks.get_center()
            # 调整 ticks 位置
            ticks.shift(self.shift_vector)

        # 绘制实际雷达图数据
        hexagon_vertices = []
        for i, attr in enumerate(self.attributes):
            value = player_data[attr]  # 选手当前属性的数值
            hexagon_vertices.append(self.polar_to_cartesian(i, value, *self.attribute_ranges[attr]) * self.radar_size)

        if player_data['is_top']:
            color_theme = self.highlight_color
        else:
            color_theme = self.normal_color

        radar_chart = (Polygon(*hexagon_vertices)
                       .set_stroke(width=5, color=color_theme).set_fill(color_theme, opacity=0.2))
        radar_chart.set_glow(2)  # 加入辉光效果

        # 将 radar_chart 的原点移动到背景矩形的中心
        radar_chart.shift(self.shift_vector)

        # 为每个顶点添加属性标签并为每个属性标签添加属性值
        labels, value_labels, marks = self._draw_labels(player_data)
        # labels = VGroup()
        # value_labels = VGroup()
        # for i, attr in enumerate(self.attributes):
        #     # 计算顶点的坐标，使用最大值的位置
        #     pos = self.polar_to_cartesian(i, max(self.attribute_ranges[attr]),
        #                                   *self.attribute_ranges[attr]) * self.radar_size
        #     # 创建文字对象并将其放置在顶点旁边
        #     if i in (5, 0, 1):
        #         pos[1] += 0.3
        #     if i in (2, 3, 4):
        #         pos[1] -= 0.3
        #     if i in (1, 2):
        #         pos[0] += 0.3
        #     if i in (4, 5):
        #         pos[0] -= 0.5
        #     if attr == 'FirstKillsPerRound':
        #         label = Text('FirstKill').scale(0.5).move_to(pos)
        #     else:
        #         label = Text(attr).scale(0.5).move_to(pos)
        #     labels.add(label)
        #     # 创建数字对象并将其放置在文字标签右边
        #     if player_data[attr] < 1:
        #         value_label = Text(str(float(np.format_float_scientific(player_data[attr], 1, trim='k')))).scale(0.8)
        #     else:
        #         value_label = Text(str(float(np.format_float_scientific(player_data[attr], 2, trim='k')))).scale(0.8)
        #     value_labels.add(value_label)
        labels.shift(self.shift_vector)
        value_labels.shift(self.shift_vector)
        marks.shift(self.shift_vector)
        # for i, value_label in enumerate(value_labels):
        #     value_label.next_to(labels[i], RIGHT)  # ��数字对象放置在文字标签右��
        #     if i == 4:
        #         value_label.next_to(labels[i], DOWN)
        #     elif i == 5:
        #         value_label.next_to(labels[i], DOWN)
        # 设置层级
        radar_chart.set_z_index(0)
        labels.set_z_index(1)
        value_labels.set_z_index(1)

        # 播放刻度
        if self.ticks is None:
            ticks_animation = AnimationGroup(
                *[GrowFromCenter(tick) for tick in ticks],  # 使用生成的对象创建动画
                lag_ratio=0.15  # 设置每个动画之间的����
            )
        # 设置雷达图动画
        if self.radar_chart is None:
            radar_chart_animation = DrawBorderThenFill(radar_chart)
            self.radar_chart = radar_chart
        else:
            radar_chart_animation = Transform(self.radar_chart, radar_chart)
            # self.radar_chart = radar_chart 这里不再需要
        # 设置雷达图标签动画
        label_animation = AnimationGroup(
            AnimationGroup(
                *list(zip([FadeIn(label) for label in labels], [Write(value_label) for value_label in value_labels])),
                lag_ratio=0.1),
            *[Write(mark) for mark in marks],
            lag_ratio=0.5)
        # 播放雷达图和雷达图标签
        if self.ticks is None:
            left_animation = AnimationGroup(
                ticks_animation,
                radar_chart_animation,
                label_animation,
                lag_ratio=0.5)
        else:
            left_animation = AnimationGroup(
                radar_chart_animation,
                label_animation,
                lag_ratio=0.3)
        if self.ticks is None:
            self.ticks = ticks
        self.labels = labels
        self.value_labels = value_labels
        self.marks = marks
        return left_animation

    def _draw_ticks(self):
        ticks = VGroup()
        num_scales = 7
        for scale_index in range(1, num_scales):
            scale_value = scale_index / (num_scales - 1)  # 从0到1的比例
            hexagon_vertices = []
            for i, attr in enumerate(self.attributes):
                min_value, max_value = self.attribute_ranges[attr]  # 获取当前属性的最小和最大值
                scale_val = min_value + scale_value * (max_value - min_value)  # 当前标度值
                hexagon_vertices.append(self.polar_to_cartesian(i, scale_val, min_value, max_value) * self.radar_size)

            # 绘制标度六边形
            hexagon = Polygon(*hexagon_vertices)
            if scale_index == 2:
                pass
            if scale_index == num_scales - 1:
                hexagon.set_stroke(width=5, color=BLUE)  # 最小和最大标度加粗
                hexagon.set_glow(2)  # 加入辉光效果
            else:
                hexagon.set_stroke(width=2, color=WHITE)  # 其他标度使用不同的颜色
            ticks.add(hexagon)
        return ticks

    def _draw_labels(self, player_data=None, max_ticks=False, min_ticks=False):
        # 为每个顶点添加属性标签并为每个属性标签添加属性值
        labels = VGroup()
        value_labels = VGroup()
        marks = VGroup()
        for i, attr in enumerate(self.attributes):
            # 计算顶点的坐标，使用最大值的位置
            pos = self.polar_to_cartesian(i, max(self.attribute_ranges[attr]),
                                          *self.attribute_ranges[attr]) * self.radar_size
            original_pos = pos
            # 创建文字对象并将其放置在顶点旁边
            if i in (5, 0, 1):
                pos[1] += 0.3
            if i in (2, 3, 4):
                pos[1] -= 0.3
            if i in (1, 2):
                pos[0] += 0.5
            if i in (4, 5):
                pos[0] -= 0.5
            if attr == 'FirstKillsPerRound':
                label = Text('FirstKill').scale(0.5).move_to(pos)
            else:
                label = Text(attr).scale(0.5).move_to(pos)
            # 创建数字对象并将其放置在文字标签右边
            if player_data is not None:
                if player_data[f'{attr}_rank'] == 1:
                    paras = {
                        'font': 'Bodoni MT Black',
                        'slant': ITALIC,
                        # 'width': BOLD
                    }
                else:
                    paras = {
                    }
                if player_data[attr] < 1:
                    value_label = Text(str(float(np.format_float_scientific(player_data[attr], 1, trim='k'))),
                                       **paras).scale(0.8)
                else:
                    value_label = Text(str(float(np.format_float_scientific(player_data[attr], 2, trim='k'))),
                                       **paras).scale(0.8)
                # ��数字对象放置在文字标签右��
                value_label.next_to(label, RIGHT)
                if i == 4:
                    value_label.next_to(label, DOWN)
                elif i == 5:
                    value_label.next_to(label, DOWN)
                # top 1
                if player_data[f'{attr}_rank'] == 1:
                    label.set_stroke(color=self.highlight_color)
                    label.scale(1.2)
                    value_label.set_stroke(color=self.highlight_color, width=1)
                    value_label.scale(1.4)
                    best_label = Text('Best', font='Bodoni MT Black', slant=ITALIC, stroke_color=self.highlight_color,
                                      stroke_width=3, stroke_opacity=0.5).scale(1).move_to(original_pos)
                    best_label.next_to(value_label, UP)
                    if i == 4:
                        best_label.next_to(label, UP)
                    elif i == 5:
                        best_label.next_to(label, UP)
                    marks.add(best_label)
                value_labels.add(value_label)
            elif max_ticks:
                value_label = Text(str(np.round(max(self.attribute_ranges[attr]), 1))).scale(0.8)
                value_labels.add(value_label)
            elif min_ticks:
                value_label = Text(str(np.round(min(self.attribute_ranges[attr]), 1))).scale(0.8)
                value_labels.add(value_label)
            else:
                pass
            labels.add(label)

        for i, value_label in enumerate(value_labels):
            value_label.next_to(labels[i], RIGHT)  # ��数字对象放置在文字标签右��
            if i == 4:
                value_label.next_to(labels[i], DOWN)
            elif i == 5:
                value_label.next_to(labels[i], DOWN)
        return labels, value_labels, marks

    def show_player_id(self, player_data, player_icon):
        # 获取选手ID
        player_id = player_data['ID']

        if player_data['is_top']:
            color_theme = self.highlight_color
        else:
            color_theme = BLUE
        # 创建文本对象，显示选手ID
        player_id_text_stroke = Text(player_id, font_size=72, font="Microsoft YaHei", weight=BOLD, slant=ITALIC,
                                     stroke_width=3,
                                     stroke_color=color_theme,
                                     fill_opacity=0,
                                     ).scale(1.4)
        player_id_text = Text(player_id, font_size=72, font="Microsoft YaHei", weight=BOLD, slant=ITALIC,
                              color=WHITE).scale(1.2)
        # player_id_text_stroke.set_color_by_gradient(self.highlight_color, WHITE)

        player_id_text.set_z_index(3)
        player_id_text_stroke.set_z_index(2)

        player_id_text.next_to(player_icon, UP, buff=1.0).shift(LEFT*0.8)
        player_id_text_stroke.next_to(player_icon, UP, buff=0.8)
        player_id_text_stroke.shift(RIGHT * 0.5)

        animation_in = AnimationGroup(
            Write(player_id_text),
            Write(player_id_text_stroke, run_time=2),
            lag_ratio=1.2
        )
        animation_out = AnimationGroup(
            FadeOut(player_id_text),
            FadeOut(player_id_text_stroke),
            lag_ratio=0.3
        )
        return animation_in, animation_out

    @staticmethod
    def analyze_animation_group(anim_group):
        """
        计算AnimationGroup的总播放时间，并输出每个动画的开始时间列表，考虑lag_ratio的影响。

        参数:
        - anim_group: AnimationGroup 对象

        返回:
        - total_time: 动画组的总持续时间
        - start_times: 每条动画的开始时间列表
        """
        if not isinstance(anim_group, AnimationGroup):
            raise TypeError("Input must be an AnimationGroup.")

        lag_ratio = anim_group.lag_ratio  # 获取lag_ratio
        start_times = []  # 初始化动画开始时间列表
        current_time = 0  # 当前时间指针

        for anim in anim_group.animations:
            start_times.append(current_time)  # 记录当前动画的开始时间
            current_time += anim.run_time * lag_ratio  # 计算下一个动画的开始时间

        # 动画组的总时间取决于最后一个动画的开始时间和持续时间
        total_time = max(start_times[i] + anim_group.animations[i].run_time for i in range(len(anim_group.animations)))

        return total_time, start_times


    def preprocess_player_data(self, csv_path):
        """
        预处理玩家数据，自动识别需要排名的列（除去 'ID' 列），并添加一列标识玩家是否在任何排名中为第一。

        参数:
        - csv_data: 字符串形式的CSV数据

        返回:
        - df: 带有排名列和"是否为第一"列的Pandas DataFrame
        """
        # 读取CSV数据
        df = pd.read_csv(csv_path)

        # 对每一列从大到小排名，并创建新列存储排名结果
        for col in self.attributes:
            df[f'{col}_rank'] = df[col].rank(ascending=False, method='min')

        # 添加一个新列，检查是否该玩家在任何排名中为1
        rank_columns = [col for col in df.columns if '_rank' in col]
        df['is_top'] = (df[rank_columns] == 1).any(axis=1).astype(int)
        return df


"""
manim -pql --format=mov --transparent cs_radar_chart.py PlayerRadarChart

manim -pql cs_radar_chart.py PlayerRadarChart

manim -pqh cs_radar_chart.py PlayerRadarChart
"""

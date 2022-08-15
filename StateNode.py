import numpy as np


class StateNode:
    def __init__(self, state, step, line, agent, episode, ou_noise, train_flag, train_model):
        self.line = line  # 区间
        self.train_model = train_model  # 列车模型
        self.agent = agent  # 神经网络
        self.ou_noise = ou_noise  # OU噪声
        self.state = state  # 当前状态 ,0是时间，1是速度
        self.acc = 0  # 当前合加速度
        self.tm_acc = 0  # 电机牵引加速度
        self.bm_acc = 0  # 电机制动加速度
        self.g_acc = 0  # 坡度加速度
        self.c_acc = 0  # 曲率加速度
        self.action = np.array(0).reshape(1)  # 当前牵引制动力请求百分比
        self.step = step  # 当前阶段
        self.episode = episode  # 当前幕数
        self.current_reward = 0  # 当前奖励
        self.current_q = 0  # 当前Q值
        self.last_node_state = 0  # 前一个节点的状态
        self.last_node_action = 0  # 前一个节点的动作
        self.last_node_acc = 0  # 前一个节点的加速度
        self.next_state = np.zeros(2)  # 状态转移后的状态
        self.t_power = 0.0  # 状态转移过程的牵引能耗
        self.re_power = 0  # 状态转移过程产生的再生制动能量
        self.train_flag = train_flag  # 训练测试标志位
        self.comfort_punish = 0  # 舒适度惩罚标志位
        self.speed_punish = 0  # 超速惩罚标志位
        self.current_limit_speed = 0  # 当前限速
        self.ave_v = 0  # 本阶段平均速度

    def get_last_node(self, node_list):  # 获取上一个节点的状态、动作加速度
        if len(node_list) != 1:
            self.last_node_state = node_list[self.step - 1].state
            self.last_node_action = node_list[self.step - 1].action
            self.last_node_acc = node_list[self.step - 1].acc
        else:
            self.last_node_state = np.zeros(2)
            self.last_node_action = np.array(0).reshape(1)
            self.last_node_acc = 0

    # 下面是动作的产生过程
    def get_action(self):  # 选择动作
        if self.train_flag:
            if self.episode > 100:
                self.action = self.agent.choose_action(self.state)
                self.action = np.array(self.action).reshape(1)
                self.action = self.ou_noise.get_action(self.action, self.step)
            else:
                self.action = np.array(np.random.uniform(-1, 1)).reshape(1)
        else:
            self.action = self.agent.choose_action(self.state)
            self.action = np.array(self.action).reshape(1)

    def reshape_action(self):  # 重整动作
        low_bound = -1
        upper_bound = 1
        # 重整当前动作
        self.action = low_bound + (self.action + 1.0) * 0.5 * (upper_bound - low_bound)
        self.action = np.clip(self.action, low_bound, upper_bound)
        # 重整上一个节点的动作，这句话好像可以不要
        self.last_node_action = low_bound + (self.last_node_action + 1.0) * 0.5 * (upper_bound - low_bound)
        self.last_node_action = np.clip(self.last_node_action, low_bound, upper_bound)

    # 下面是合加速度的计算过程
    def get_gradient_acc(self):  # 获取当前位置坡度加速度
        key_list = []
        key = 0
        for i in self.line.gradient.keys():
            key_list.append(i)
        for j in range(len(key_list) - 1):
            if key_list[j] <= self.step * self.line.delta_distance < key_list[j + 1]:
                key = key_list[j]
        gradient = self.line.gradient[key]
        self.g_acc = 9.8 * gradient / 1000  # g_ acc = 9.8 * g /1000
        del key_list

    def get_curve_acc(self):  # 获取当前位置曲率加速度
        key_list = []
        key = 0
        for i in self.line.curve.keys():
            key_list.append(i)
        for j in range(len(key_list) - 1):
            if key_list[j] <= self.step * self.line.delta_distance < key_list[j + 1]:
                key = key_list[j]
        curve = self.line.curve[key]
        if curve != 0:
            self.c_acc = - 3 * 9.8 / (5 * curve)  # c_acc = 3g/5R
        else:
            self.c_acc = 0
        del key_list

    def get_current_tra_acc(self):  # 计算当前牵引加速度
        self.train_model.get_max_traction_force(self.state[1])  # 当前车辆的最大牵引力
        tra_force = self.train_model.max_traction_force * self.action  # 当前输出的牵引力
        self.tm_acc = tra_force / self.train_model.weight

    def get_current_b_acc(self):  # 计算当前制动加速度
        self.train_model.get_max_brake_force(self.state[1])
        bra_force = self.train_model.max_brake_force * abs(self.action)  # 单位是kN
        self.bm_acc = - bra_force / self.train_model.weight

    def get_m_acc(self):  # 判断当前是制动还是牵引
        if self.action < 0:
            self.tm_acc = 0
            self.get_current_b_acc()
        else:
            self.get_current_tra_acc()
            self.bm_acc = 0

    def get_acc(self):
        self.get_m_acc()
        self.get_gradient_acc()
        self.get_curve_acc()
        self.acc = self.tm_acc + self.bm_acc + self.g_acc + self.c_acc

    # 下面是能耗的计算过程
    def get_ave_v(self):  # 获取平均速度
        self.ave_v = 0.5 * (self.state[1] + self.next_state[1])

    def get_t_power(self):
        delta_t = self.next_state[0] - self.state[0]
        self.t_power = self.train_model.get_traction_power(self.ave_v, delta_t, self.action)

    def get_re_power(self):
        delta_t = self.next_state[0] - self.state[0]
        self.re_power = self.train_model.get_re_power(self.ave_v, delta_t, self.action)

    def get_power(self):
        self.get_ave_v()
        if self.action <= 0:
            self.t_power = 0
            self.get_re_power()
        else:
            self.re_power = 0
            self.get_t_power()

    # 下面是超速检查过程
    def get_limit_speed(self):
        key_list = []
        key = 0
        for i in self.line.speed_limit.keys():
            key_list.append(i)
        for j in range(len(key_list) - 1):
            if key_list[j] <= self.step * self.line.delta_distance < key_list[j + 1]:
                key = key_list[j]
        limit_speed = self.line.speed_limit[key]
        if self.state[1] >= limit_speed:  # 超速
            self.speed_punish = 1
            self.current_limit_speed = limit_speed
        else:
            self.speed_punish = 0
            self.current_limit_speed = limit_speed

    # 下面是舒适度检查过程
    def comfort_check(self):
        if abs(self.acc - self.last_node_acc) >= 0.3:
            self.comfort_punish = 1  # 不舒适
        else:
            self.comfort_punish = 0

    def get_current_q(self):  # 获取当前Q值
        self.current_q = self.agent.target_critic(self.state, self.action.detach())
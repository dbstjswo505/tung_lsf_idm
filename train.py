import numpy as np
import torch
import argparse
import os
import math
import gym
import sys
import random
import time
import json
import dmc2gym
import copy
from tqdm import tqdm

import utils
from utils import str2bool
from logger import Logger
from video import VideoRecorder

from agent.sac_ae import SacAeAgent
from agent.sac_curl import SacCurlAgent
from agent.sac_rad import SacRadAgent
from agent.sac_cpm import SacCPMAgent
from agent.sac_drq import SacDrqAgent
from agent.sac_aux import SacAuxAgent
from agent.sac_drq_lsf import SacLSFAgent
from agent.sac_rad_lsf import SacRadLSFAgent

def parse_args():
    parser = argparse.ArgumentParser()
    # environment
    parser.add_argument('--benchmark', default='planet', type=str, choices=['dreamer', 'planet', 'ours'])
    parser.add_argument('--domain_name', default='cheetah')
    parser.add_argument('--task_name', default='run')
    parser.add_argument('--image_size', default=84, type=int)
    parser.add_argument('--action_repeat', default=-1, type=int)
    parser.add_argument('--frame_stack', default=3, type=int)
    # Distractor environment
    parser.add_argument('--difficulty', default='easy', type=str, choices=['easy', 'medium', 'hard'])
    parser.add_argument('--bg_dataset_path', default='/home/tung/workspace/rlbench/DAVIS/JPEGImages/480p/', type=str)
    parser.add_argument('--bg_dynamic', action='store_true')
    parser.add_argument('--rand_bg', action='store_true')
    parser.add_argument('--rand_cam', action='store_true')
    parser.add_argument('--rand_color', action='store_true')

    parser.add_argument('--pre_transform_image_size', default=100, type=int)
    # RAD
    parser.add_argument('--data_augs', default='crop', type=str)
    # CURL
    parser.add_argument('--cpc_update_freq', default=1, type=int)
    # CPM
    parser.add_argument('--idm_update_freq', default=1, type=int)
    parser.add_argument('--cpm_noaug', action='store_true', default=False)
    # Leveraging skipped frames (LSF)
    parser.add_argument('--n_extra_update_cri', default=1, type=int)
    parser.add_argument('--use_lsf', type=str2bool, default=False)
    parser.add_argument('--use_aug', type=str2bool, default=True)
    parser.add_argument('--n_inv_updates', default=2, type=int)

    # Linearized FDM
    parser.add_argument('--fdm_lr', default=1e-3, type=float)
    parser.add_argument('--fdm_arch', default='linear', type=str)
    parser.add_argument('--sim_metric', default='bilinear', type=str, choices=['bilinear', 'inner'])

    parser.add_argument('--error_weight', default=1.0, type=float)
    parser.add_argument('--fdm_error_coef', default=1.0, type=float)
    parser.add_argument('--fdm_pred_coef', default=1.0, type=float)

    parser.add_argument('--use_act_encoder', type=str2bool, default=False)
    parser.add_argument('--detach_encoder', type=str2bool, default=False)
    parser.add_argument('--detach_mlp', type=str2bool, default=False)
    parser.add_argument('--share_mlp_ac', type=str2bool, default=False)
    # replay buffer
    parser.add_argument('--replay_buffer_capacity', default=100000, type=int)
    # train
    parser.add_argument('--agent', default='sac_aux', type=str)
    parser.add_argument('--init_steps', default=1000, type=int)
    parser.add_argument('--num_train_steps', default=1000000, type=int)
    parser.add_argument('--num_train_envsteps', default=-1, type=int)
    parser.add_argument('--batch_size', default=128, type=int)
    parser.add_argument('--hidden_dim', default=1024, type=int)
    # eval
    parser.add_argument('--eval_freq', default=10000, type=int)
    parser.add_argument('--num_eval_episodes', default=10, type=int)
    # critic
    parser.add_argument('--critic_lr', default=1e-3, type=float)
    parser.add_argument('--critic_beta', default=0.9, type=float)
    parser.add_argument('--critic_tau', default=0.01, type=float)
    parser.add_argument('--critic_target_update_freq', default=2, type=int)
    # actor
    parser.add_argument('--actor_lr', default=1e-3, type=float)
    parser.add_argument('--actor_beta', default=0.9, type=float)
    parser.add_argument('--actor_log_std_min', default=-10, type=float)
    parser.add_argument('--actor_log_std_max', default=2, type=float)
    parser.add_argument('--actor_update_freq', default=2, type=int)
    # encoder/decoder
    parser.add_argument('--encoder_type', default='pixel', type=str)
    parser.add_argument('--encoder_feature_dim', default=50, type=int)
    parser.add_argument('--encoder_lr', default=1e-3, type=float)
    parser.add_argument('--encoder_tau', default=0.05, type=float)
    parser.add_argument('--decoder_type', default='pixel', type=str)
    parser.add_argument('--decoder_lr', default=1e-3, type=float)
    parser.add_argument('--decoder_update_freq', default=1, type=int)
    parser.add_argument('--decoder_latent_lambda', default=1e-6, type=float)
    parser.add_argument('--decoder_weight_lambda', default=1e-7, type=float)
    parser.add_argument('--num_layers', default=4, type=int)
    parser.add_argument('--num_filters', default=32, type=int)
    # sac
    parser.add_argument('--n_grad_updates', default=1, type=int)
    parser.add_argument('--discount', default=0.99, type=float)
    parser.add_argument('--init_temperature', default=0.1, type=float)
    parser.add_argument('--alpha_lr', default=1e-4, type=float)
    parser.add_argument('--alpha_beta', default=0.5, type=float)
    # misc
    parser.add_argument('--seed', default=1, type=int)
    parser.add_argument('--eval_seed', default=1, type=int)
    parser.add_argument('--work_dir', default='.', type=str)
    parser.add_argument('--exp', default='exp', type=str)
    parser.add_argument('--save_tb', default=False, action='store_true')
    parser.add_argument('--save_model', default=False, action='store_true')
    parser.add_argument('--save_buffer', default=False, action='store_true')
    parser.add_argument('--save_video', default=False, action='store_true')

    parser.add_argument('--log_interval', default=500, type=int)
    args = parser.parse_args()
    return args


def evaluate(env, agent, video, num_episodes, L, step, args):

    def preprocess_obs(obs):
        if args.agent in ['sac_curl', 'sac_cpm', 'sac_aux', 'sac_rad_lsf']:
            preprocessed = utils.center_crop_image(obs, args.image_size)  # Preprocess input for CURL
        elif args.agent in ['sac_rad']:
            # center crop image
            if 'crop' in args.data_augs:
                obs = utils.center_crop_image(obs, args.image_size)
            if 'translate' in args.data_augs:
                # first crop the center with pre_image_size
                obs = utils.center_crop_image(obs, args.pre_transform_image_size)
                # then translate cropped to center
                obs = utils.center_translate(obs, args.image_size)
            preprocessed = obs
        else:
            preprocessed = obs
        return preprocessed

    all_ep_rewards = []
    for i in range(num_episodes):
        obs = env.reset()
        video.init(enabled=(i == 0))
        done = False
        episode_reward = 0
        while not done:
            obs = preprocess_obs(obs)
            with utils.eval_mode(agent):
                action = agent.select_action(obs)
            obs, reward, done, _ = env.step(action)
            video.record(env)
            episode_reward += reward

        video.save('%d.mp4' % step)
        L.log('eval/episode_reward', episode_reward, step)
        all_ep_rewards.append(episode_reward)

    mean_ep_reward = np.mean(all_ep_rewards)
    best_ep_reward = np.max(all_ep_rewards)
    L.log('eval/mean_episode_reward', mean_ep_reward, step)
    L.log('eval/best_episode_reward', best_ep_reward, step)
    L.dump(step)


def make_agent(obs_shape, action_shape, args, device):
    if args.agent in ['sac_ae']:
        return SacAeAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            decoder_type=args.decoder_type,
            decoder_lr=args.decoder_lr,
            decoder_update_freq=args.decoder_update_freq,
            decoder_latent_lambda=args.decoder_latent_lambda,
            decoder_weight_lambda=args.decoder_weight_lambda,
            num_layers=args.num_layers,
            num_filters=args.num_filters
        )
    elif args.agent in ['sac_curl']:
        return SacCurlAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
        )
    elif args.agent in ['sac_cpm']:
        return SacCPMAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
            cpc_update_freq=args.cpc_update_freq,
            idm_update_freq=args.idm_update_freq,
            no_aug=args.cpm_noaug
        )
    elif args.agent in ['sac_rad']:
        return SacRadAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
            data_augs=args.data_augs
        )
    elif args.agent in ['sac_drq']:
        return SacDrqAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
        )
    elif args.agent in ['sac_aux']:
        return SacAuxAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            n_enc_updates=args.n_enc_updates,
            fdm_lr=args.fdm_lr,
            use_aug=not args.cpm_noaug,
            fdm_arch=args.fdm_arch,
            sim_metric=args.sim_metric,
            fdm_error_coef=args.fdm_error_coef,
            fdm_pred_coef=args.fdm_pred_coef,
            use_act_encoder=args.use_act_encoder,
            detach_encoder=args.detach_encoder,
            detach_mlp=args.detach_mlp,
            share_mlp_ac=args.share_mlp_ac,
        )
    elif args.agent in ['sac_drq_lsf']:
        return SacLSFAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            decoder_lr=args.decoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
        )
    elif args.agent in ['sac_rad_lsf']:
        return SacRadLSFAgent(
            obs_shape=obs_shape,
            action_shape=action_shape,
            device=device,
            hidden_dim=args.hidden_dim,
            discount=args.discount,
            init_temperature=args.init_temperature,
            alpha_lr=args.alpha_lr,
            alpha_beta=args.alpha_beta,
            actor_lr=args.actor_lr,
            actor_beta=args.actor_beta,
            actor_log_std_min=args.actor_log_std_min,
            actor_log_std_max=args.actor_log_std_max,
            actor_update_freq=args.actor_update_freq,
            critic_lr=args.critic_lr,
            critic_beta=args.critic_beta,
            critic_tau=args.critic_tau,
            critic_target_update_freq=args.critic_target_update_freq,
            encoder_type=args.encoder_type,
            encoder_feature_dim=args.encoder_feature_dim,
            encoder_lr=args.encoder_lr,
            decoder_lr=args.decoder_lr,
            encoder_tau=args.encoder_tau,
            num_layers=args.num_layers,
            num_filters=args.num_filters,
            log_interval=args.log_interval,
            detach_encoder=args.detach_encoder,
            batch_size=args.batch_size,
            action_repeat=args.action_repeat,
            use_aug=args.use_aug
        )
    else:
        assert 'agent is not supported: %s' % args.agent


def make_env(args, mode='train', **kwargs):
    ar_planet_benchmark = dict(
        cartpole=8, cheetah=4, ball_in_cup=4, reacher=4, walker=2, finger=2,
        hopper=4, pendulum=4
    )
    ours_benchmark = dict(
        reach_duplo=2,
    )
    episode_length = 250 if args.benchmark == 'ours' else 1000
    if args.encoder_type == 'pixel' and args.action_repeat == -1:
        if args.benchmark == 'planet':
            args.__dict__["action_repeat"] = ar_planet_benchmark[args.domain_name]
        elif args.benchmark == 'dreamer':
            args.__dict__["action_repeat"] = 2
        elif args.benchmark == 'ours':
            args.__dict__["action_repeat"] = ours_benchmark[args.task_name]
    elif args.encoder_type == 'identity':
        args.__dict__["action_repeat"] = 1

    env_args = dict(
        domain_name=args.domain_name,
        task_name=args.task_name,
        seed=args.seed,
        visualize_reward=False,
        from_pixels=(args.encoder_type == 'pixel'),
        height=args.image_size,
        width=args.image_size,
        frame_skip=args.action_repeat,
        difficulty=args.difficulty,
        background_dataset_path=args.bg_dataset_path,
        background_dataset_videos=mode,
        dynamic=args.bg_dynamic,
        default_background=not args.rand_bg,
        default_camera=not args.rand_cam,
        default_color=not args.rand_color,
        episode_length=episode_length
    )

    if args.encoder_type == 'identity':
        assert args.agent in ['sac_ae'], 'If you use state, please use `sac_ae` agent.'

    if args.agent in ['sac_ae', 'sac_drq', 'sac_drq_lsf']:
        env_args.update(
            height=args.image_size,
            width=args.image_size,
        )
    elif args.agent in ['sac_curl', 'sac_cpm', 'sac_aux', 'sac_rad_lsf']:
        env_args.update(
            height=args.pre_transform_image_size,
            width=args.pre_transform_image_size,
        )
    elif args.agent in ['sac_rad']:
        pre_transform_image_size = args.pre_transform_image_size if 'crop' in args.data_augs else args.image_size
        env_args.update(
            height=pre_transform_image_size,
            width=pre_transform_image_size,
        )
    else:
        assert 'agent is not supported: %s' % args.agent
    return dmc2gym.make(**env_args)


def make_replaybuffer(args, env, device=torch.device('cpu')):
    pre_aug_obs_shape = env.observation_space.shape
    if args.encoder_type == 'pixel':
        if args.agent in ['sac_curl', 'sac_cpm', 'sac_aux']:
            pre_aug_obs_shape = (3 * args.frame_stack, args.pre_transform_image_size, args.pre_transform_image_size)
        elif args.agent in ['sac_rad']:
            pre_transform_image_size = args.pre_transform_image_size if 'crop' in args.data_augs else args.image_size
            pre_aug_obs_shape = (3 * args.frame_stack, pre_transform_image_size, pre_transform_image_size)

    if args.agent in ['sac_ae']:
        return utils.ReplayBuffer(
            obs_shape=pre_aug_obs_shape,
            action_shape=env.action_space.shape,
            capacity=args.replay_buffer_capacity,
            batch_size=args.batch_size,
            device=device
        )
    elif args.agent in ['sac_aux', 'sac_drq_lsf', 'sac_rad_lsf']:
        return utils.LSFReplayBuffer(
            obs_shape=pre_aug_obs_shape,
            action_shape=env.action_space.shape,
            capacity=args.replay_buffer_capacity,
            batch_size=args.batch_size,
            device=device,
            action_repeat=args.action_repeat,
            use_lsf=args.use_lsf
        )
    elif args.agent in ['sac_curl', 'sac_cpm']:
        return utils.CurlReplayBuffer(
            obs_shape=pre_aug_obs_shape,
            action_shape=env.action_space.shape,
            capacity=args.replay_buffer_capacity,
            batch_size=args.batch_size,
            image_size=args.image_size,
            device=device,
        )
    elif args.agent in ['sac_rad']:
        pre_image_size = args.pre_transform_image_size  # record the pre transform image size for translation
        return utils.RadReplayBuffer(
            obs_shape=pre_aug_obs_shape,
            action_shape=env.action_space.shape,
            capacity=args.replay_buffer_capacity,
            batch_size=args.batch_size,
            image_size=args.image_size,
            pre_image_size=pre_image_size,
            device=device,
        )
    elif args.agent in ['sac_drq']:
        return utils.DrQReplayBuffer(
            obs_shape=pre_aug_obs_shape,
            action_shape=env.action_space.shape,
            capacity=args.replay_buffer_capacity,
            batch_size=args.batch_size,
            image_pad=4,
            device=device,
        )
    else:
        assert 'agent is not supported: %s' % args.agent


def main():
    args = parse_args()
    if args.seed == -1:
        args.__dict__["seed"] = np.random.randint(1, 1000000)
    utils.set_seed_everywhere(args.seed)

    env = make_env(args, mode='train')
    env.seed(args.seed)
    eval_env = make_env(args, mode='train')
    eval_env_seed = dict(
        cheetah=[2, 10]
    )
    if args.domain_name in eval_env_seed.keys():
        eval_seed = int(np.random.choice(eval_env_seed[args.domain_name]))
    else:
        eval_seed = args.seed
    args.__dict__["eval_seed"] = eval_seed
    eval_env.seed(eval_seed)

    # stack several consecutive frames together
    if args.encoder_type == 'pixel':
        env = utils.FrameStack(env, k=args.frame_stack, ar=args.action_repeat)
        eval_env = utils.FrameStack(eval_env, k=args.frame_stack, ar=args.action_repeat)

    utils.make_logdir(args)
    video_dir = utils.make_dir(os.path.join(args.work_dir, 'video'))
    model_dir = utils.make_dir(os.path.join(args.work_dir, 'model'))
    buffer_dir = utils.make_dir(os.path.join(args.work_dir, 'buffer'))

    video = VideoRecorder(video_dir if args.save_video else None)

    with open(os.path.join(args.work_dir, 'args.json'), 'w') as f:
        json.dump(vars(args), f, sort_keys=True, indent=4)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # the dmc2gym wrapper standardizes actions
    assert env.action_space.low.min() >= -1
    assert env.action_space.high.max() <= 1

    if args.encoder_type == 'pixel':
        obs_shape = (3 * args.frame_stack, args.image_size, args.image_size)
    elif args.encoder_type == 'identity':
        obs_shape = env.observation_space.shape
    else:
        obs_shape = None
        assert 'Encoder is not supported: %s' % args.encoder_type

    replay_buffer = make_replaybuffer(
        env=env,
        args=args,
        device=device
    )

    agent = make_agent(
        obs_shape=obs_shape,
        action_shape=env.action_space.shape,
        args=args,
        device=device
    )

    L = Logger(args.work_dir, use_tb=args.save_tb, action_repeat=args.action_repeat)

    if args.num_train_envsteps != -1:
        # Override N training step if args.num_train_envsteps is given
        args.num_train_steps = int(args.num_train_envsteps / args.action_repeat)

    episode, episode_reward, done = 0, 0, True
    eval_freq = int(args.eval_freq / args.action_repeat)    # Freq compatible with environment steps
    start_time = time.time()
    first_step= True
    for step in tqdm(range(args.num_train_steps + 1)):
        if done:
            if step > 0:
                L.log('train/duration', time.time() - start_time, step)
                start_time = time.time()
                L.dump(step)

            # evaluate agent periodically
            if step % eval_freq == 0:
                print('[INFO] {}-{}: {} - seed: {}'.format(args.domain_name, args.task_name,
                                                           args.exp,
                                                           args.seed))
                L.log('eval/episode', episode, step)
                evaluate(eval_env, agent, video, args.num_eval_episodes, L, step, args)
                if args.save_model or step == args.num_train_steps or \
                    step == int(100000 / args.action_repeat) or step == int(500000 / args.action_repeat):
                    agent.save(model_dir, step)
                if args.save_buffer:
                    replay_buffer.save(buffer_dir)

            if step % args.log_interval == 0:
                L.log('train/episode_reward', episode_reward, step)

            obs = env.reset()
            done = False
            episode_reward = 0
            episode_step = 0
            episode += 1
            first_step = True
            extra = None

            if step % args.log_interval == 0:
                L.log('train/episode', episode, step)

        # sample action for data collection
        if step < args.init_steps:
            action = env.action_space.sample()
        else:
            with utils.eval_mode(agent):
                action = agent.sample_action(obs)

        # run training update
        if step >= args.init_steps:
            # TODO: our method
            if step == args.init_steps:
                if args.use_lsf:
                    for _ in range(args.init_steps):
                        agent.update_dynamics_only(replay_buffer, L, step)
            else:
                # num_updates = args.n_grad_updates
                # for i in range(num_updates):
                agent.update(replay_buffer, L, step, use_lsf=args.use_lsf,
                             n_inv_updates=args.n_inv_updates)
                for _ in range(args.n_extra_update_cri):
                    if args.use_lsf:
                        agent.update_critic_use_sf(replay_buffer, L, step)
                    else:
                        agent.update_critic_use_original_data(replay_buffer, L, step)
            # TODO: for ablation
            # agent.update(replay_buffer, L, step, use_lsf=args.use_lsf,
            #              n_inv_updates=args.n_inv_updates)
            # TODO: previous method
            # agent.update(replay_buffer, L, step, use_lsf=args.use_lsf,
            #              n_inv_updates=args.n_inv_updates)
            # for _ in range(args.n_extra_update_cri):
            #     agent.update_critic_use_sf_previous_method(replay_buffer, L, step)


        next_obs, reward, done, next_extra = env.step(action)

        # allow infinite bootstrap
        done = float(done)
        done_no_max = 0 if episode_step + 1 == env._max_episode_steps else float(done)
        episode_reward += reward

        replay_buffer.add(obs, action, reward, next_obs, done, done_no_max,
                          extra, next_extra, first_step)

        obs = next_obs
        episode_step += 1
        first_step = False
        extra = next_extra


if __name__ == '__main__':
    main()

import argparse
import time
from pathlib import Path

import cv2
import torch
import torch.backends.cudnn as cudnn
from numpy import random

from models.experimental import attempt_load
from utils.datasets import LoadStreams, LoadImages
from utils.general import check_img_size, check_requirements, non_max_suppression, apply_classifier, scale_coords, \
    xyxy2xywh, strip_optimizer, set_logging, increment_path
from utils.plots import plot_one_box
from utils.torch_utils import select_device, load_classifier, time_synchronized

from single_word.cnn_net import Net
from single_word.utils import Tools
from PIL import Image
import numpy as np
import csv
tools = Tools('single_word/data/')

def detect(save_img=False):
    source, weights, view_img, save_txt, imgsz = opt.source, opt.weights, opt.view_img, opt.save_txt, opt.img_size
    # Directories
    #save_dir = Path(increment_path(Path(opt.project) / opt.name, exist_ok=opt.exist_ok))  # increment run
    save_dir = Path(Path(opt.project) / opt.name, exist_ok=opt.exist_ok)  # increment run
    (save_dir / 'labels' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    # Initialize
    set_logging()
    device = select_device(opt.device)
    half = device.type != 'cpu'  # half precision only supported on CUDA

    # Load model
    model = attempt_load(weights, map_location=device)  # load FP32 model
    imgsz = check_img_size(imgsz, s=model.stride.max())  # check img_size
    if half:
        model.half()  # to FP16

    modelc = torch.load('single_word/weights/cnn.pt')

    save_img = True
    dataset = LoadImages(source, img_size=imgsz)

    # Get names and colors
    names = model.module.names if hasattr(model, 'module') else model.names
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in names]

    # Run inference
    t0 = time.time()
    img = torch.zeros((1, 3, imgsz, imgsz), device=device)  # init img
    _ = model(img.half() if half else img) if device.type != 'cpu' else None  # run once
    header = ['word_path', 'content', 'font', 'author', 'work_id', 'position']
    with open('data.csv', 'a', encoding = 'UTF8') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(header)
    for path, img, im0s, vid_cap in dataset:
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Inference
        t1 = time_synchronized()
        pred = model(img, augment=opt.augment)[0]

        # Apply NMS
        pred = non_max_suppression(pred, opt.conf_thres, opt.iou_thres, classes=opt.classes, agnostic=opt.agnostic_nms)
        t2 = time_synchronized()

        single_words = []

        # Process detections
        for i, det in enumerate(pred):  # detections per image
            p, s, im0, frame = path, '', im0s, getattr(dataset, 'frame', 0)
            ppath = p[p.rfind('single_word/imgs/') + len('single_word/imgs/'):]
            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # img.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # img.txt
            s += '%gx%g ' % img.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh\
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()

                # Write results
                word_count = 0
                for *xyxy, conf, cls in reversed(det):
                    c1, c2 = (int(xyxy[0]), int(xyxy[1])), (int(xyxy[2]), int(xyxy[3]))
                    word = im0[c1[1]:c2[1], c1[0]:c2[0]] # y x
                    original_word = word.copy()
                    index, score, result = tools.evaluate_word(word, modelc)
                    result = np.array(result)
                    result = cv2.resize(result, (abs(c1[0] - c2[0]), abs(c1[1] - c2[1]))) # w h
                    im0[c1[1]:c2[1], c1[0]:c2[0]] = result
                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf, score, ch) if opt.save_conf else (cls, *xywh, score, index)  # label format
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')

                    if save_img or view_img:  # Add bbox to image
                        # label = f'{names[int(cls)]} {conf:.2f}'
                        label = f'{conf:.2f} {score*100:.2f}'
                        #plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=1)
                        dot = ppath.rfind(".")
                        save_word_path = str(save_dir / ppath[:dot] / (str(word_count) + ppath[dot:]))
                        #print(save_word_path, word.shape)
                        original_word = cv2.inRange(original_word, np.array([110, 110, 110], dtype = "uint16"), np.array([255, 255, 255], dtype = "uint16"))
                        x_boader, y_boarder = int(0.1*original_word.shape[1]), int(0.1*original_word.shape[0])
                        output_word = cv2.copyMakeBorder(original_word, y_boarder, y_boarder, x_boader, x_boader, cv2.BORDER_CONSTANT, None, [255, 255, 255])
                        output_word = cv2.resize(output_word, (100, 100), interpolation=cv2.INTER_AREA)
                        save_subdir = Path(save_word_path).parents[0]  # increment run
                        save_subdir.mkdir(parents=True, exist_ok=True)  # make dir
                        cv2.imwrite(save_word_path, output_word)
                        ### write to csv
                        word_path_relative = ppath[:dot] + "/" + str(word_count) + ppath[dot:]
                        content = None
                        font = Path(word_path_relative).parts[-4]
                        author = Path(word_path_relative).parts[-3]
                        workname = Path(word_path_relative).parts[-2]
                        xyxy_ = [int(xy) for xy in xyxy]
                        data = [word_path_relative, content, font, author, workname, xyxy_]
                        with open('data.csv', 'a', encoding = 'UTF8') as csvf:
                            writer = csv.writer(csvf)
                            writer.writerow(data)
                        print(data)
                    word_count = word_count + 1


            # Print time (inference + NMS)
            print(f'{s}Done. ({t2 - t1:.3f}s)')

            # Save results (image with detections)
            # if save_img:
            #     cv2.imwrite(save_path, im0)
    if save_txt or save_img:
        s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ''
        print(f"Results saved to {save_dir}{s}")

    print(f'Done. ({time.time() - t0:.3f}s)')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', nargs='+', type=str, default='single_word/weights/yolov5s.pt', help='model.pt path(s)')
    parser.add_argument('--source', type=str, default='single_word/imgs/', help='source')  # file/folder, 0 for webcam
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.25, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.45, help='IOU threshold for NMS')
    parser.add_argument('--device', default='', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--view-img', action='store_true', help='display results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-conf', action='store_true', help='save confidences in --save-txt labels')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--project', default='runs/detect', help='save results to project/name')
    parser.add_argument('--name', default='exp', help='save results to project/name')
    parser.add_argument('--exist-ok', action='store_true', help='existing project/name ok, do not increment')
    opt = parser.parse_args()
    print(opt)
    check_requirements()

    with torch.no_grad():
        detect()

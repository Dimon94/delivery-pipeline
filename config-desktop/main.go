package main

import (
	"github.com/egoist/mygo"
	"log"
)

func main() {
	mygo.Bind(installedHost())
	mygo.App.WhenReady(func() {
		mygo.NewWindow(mygo.WindowOptions{Title: "Delivery Pipeline · 模型设置", Width: 1100, Height: 850, MinWidth: 640, MinHeight: 620, URL: "/"})
	})
	if err := mygo.App.Run(); err != nil {
		log.Fatal(err)
	}
}

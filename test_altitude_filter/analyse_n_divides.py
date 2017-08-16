import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import os
from glob import glob
import numpy as np
import matplotlib.patches as mpatches


def make_panda(dir):
    new_count = pd.DataFrame(columns=['none', 2.0, 3.0, 4.0, 5.0, '6-10',
                                      '11-15', '16-20', '21-30', '31-55'])
    for txt in os.listdir(dir):
        if txt.endswith('.txt') and not txt.startswith('all'):
            list_count = {}

            file = pd.read_csv(os.path.join(dir, txt))

            count = file['n_divides'].value_counts()
            '''
            for j in count.index.drop(1.0):
                if j < 10:
                    list_count[j] = [count.loc[j]]
                elif j in range(10,15):
            '''
            list_count = {j:count[j] for j in count[(count.index>1)&(count.index <=5)].index}
            list_count['6-10'] = count[(count.index >= 6) & (count.index <= 10)].sum()
            list_count['11-15'] = count[(count.index >= 11) & (count.index <= 15)].sum()
            list_count['16-20'] = count[(count.index >= 16) & (count.index <= 20)].sum()
            list_count['21-30'] = count[(count.index >= 21) & (count.index <= 30)].sum()
            list_count['31-55'] = count[count.index > 30].sum()
            #list_count['none'] = count[count.index ==1.0].sum()
            #list_count = {count.index[j]:[count.iloc[j]] for j in range(1,len(count))}
            new_count = new_count.append(pd.DataFrame(list_count, columns=list_count.keys(),index=[txt.split('_')[0]+'-'+txt.split('_')[-1].split('.')[0]]), ignore_index=False)
    return new_count

def make_bar_plots(dir1,dir2):

    no_filter = make_panda(dir1)
    alt_filter = make_panda(dir2)
    no_filter['option'] = 'no filter'
    alt_filter['option'] = 'altitude filters only'
    #merged = pd.concat([no_filter,alt_filter])

    ax=no_filter.sort_index(ascending=False).plot.barh(width=0.3,fontsize=8, stacked=True,figsize=(15, 10),position=0)
    handles, labels = ax.get_legend_handles_labels()
    alt_filter.sort_index(ascending=False).plot.barh(ax=ax,width=0.3,fontsize=8, stacked=True,figsize=(15, 10),position=1,alpha=0.5,legend=False)

    ax=plt.gca().add_artist(plt.legend(handles[1:], labels[1:]))
    normal_patch = mpatches.Patch(color='orange', label='partitioning without filter')
    trans_patch = mpatches.Patch(color='orange', alpha=0.5, label='altitude filters')
    plt.legend(handles=[normal_patch,trans_patch])
    plt.title('number of divides per RGI region')
    plt.xlabel('absolute number of glaciers')
    plt.ylabel('RGI-region')


    plt.show()

    '''
    print(merged)
    merged.sort(ascending=False).plot.barh(fontsize=8, stacked=True,figsize=(15, 10))
    plt.show()



    no_filter.sort(ascending=False).plot.barh(fontsize=8, stacked=True, figsize=(15, 10))
    plt.hold
    alt_filter.sort(ascending=False).plot.barh(fontsize=8, stacked=True, figsize=(15, 10))
    plt.show()

    print(new_count.sort())


    new_count.sort(ascending=False).plot.barh(fontsize=8, stacked=True, figsize=(15,10))
    plt.title('number of divides per RGI region')
    plt.xlabel('absolute number of glaciers')
    plt.ylabel('RGI-region')
    plt.show()
    '''

def count_total_number(dir):
    '''
    total_n = pd.DataFrame(columns=['original', 'partitioning_no_filter'])
    for path in glob(dir+"/RGI50-*/"):
        file = os.path.join(path, [name for name in os.listdir(path) if name.startswith('all') and name.endswith('.shp')][0] )
        region = gpd.read_file(file)
        total_n = total_n.append(pd.DataFrame({'partitioning_no_filter': len(region)}, index=[path.split('/')[-2]]),ignore_index=False)
        print(file)

    for path2 in glob("/home/juliaeis/Dokumente/rgi50/*/*"):
        if path2.endswith('.shp') and path2.split('/')[-1].split('_')[0] != '00' :
            rgi = gpd.read_file(path2)
            total_n = total_n.set_value(index='RGI50-'+ path2.split('/')[-1].split('_')[0], col=['original'],value=len(rgi))
    print(total_n)
    total_n.to_csv('/home/juliaeis/Schreibtisch/partitioning/no_filter/all_RGI.txt')
    '''
    total_n = pd.read_csv('/home/juliaeis/Schreibtisch/partitioning/all_RGI.txt',index_col=0)

    #print(total_n)
    total_n.sort(ascending=False).plot.barh()
    plt.xlabel('total number of glaciers')
    plt.ylabel('RGI-region')
    plt.show()
    print(total_n.sum())


if __name__ == '__main__':

    make_bar_plots('/home/juliaeis/Schreibtisch/partitioning/no_filter','/home/juliaeis/Schreibtisch/partitioning/altitude_filter')
    count_total_number('/home/juliaeis/Schreibtisch/partitioning/altitude_filter')